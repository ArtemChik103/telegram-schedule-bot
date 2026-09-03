import logging
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.request import HTTPXRequest
from src.config import TELEGRAM_TOKEN, GROUP_ID, setup_logging
from src.database.db import db
from src.api.client import api_client
from src.services.notification_service import setup_scheduled_jobs
from src.services.schedule_service import calculate_schedule_hash
from src.handlers.common import (
    cmd_start,
    cmd_help,
    cmd_sync,
    cmd_bells,
    cmd_stats,
    cmd_broadcast,
)
from src.handlers.schedule import (
    handle_text_command,
    week_callback_handler,
    cmd_now,
    cmd_today,
    cmd_tomorrow,
    cmd_week,
)
from src.handlers.settings import cmd_settings, settings_callback_handler
from src.handlers.calendar import export_calendar_handler
from src.handlers.error import error_handler

logger = logging.getLogger(__name__)


async def post_init(application: Application) -> None:
    """Инициализация базы данных, фоновых задач и прогрев кэша."""
    await db.init()
    logger.info(f"Прогрев кэша расписания для группы {GROUP_ID}...")
    data, is_fallback = await api_client.get_group_schedule(GROUP_ID)
    if data:
        source = "SQLite (резерв)" if is_fallback else "API АмГУ"
        logger.info(f"Расписание успешно загружено ({source}).")
        # Фиксируем начальный слепок расписания для чекера diff, если еще нет
        if not is_fallback:
            existing_snapshot = await db.get_schedule_snapshot(GROUP_ID)
            if existing_snapshot is None:
                s_hash = calculate_schedule_hash(data)
                await db.save_schedule_snapshot(GROUP_ID, s_hash, data)
    else:
        logger.warning("Не удалось загрузить расписание при старте.")

    # Настройка фоновых задач JobQueue
    setup_scheduled_jobs(application)


async def post_shutdown(application: Application) -> None:
    """Корректное освобождение ресурсов при остановке бота."""
    logger.info("Завершение работы: закрытие соединений...")
    await api_client.close()
    await db.close()


def create_application() -> Application:
    """Создает и настраивает экземпляр Telegram Application."""
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "ВАШ_ТОКЕН":
        raise ValueError(
            "TELEGRAM_BOT_TOKEN не задан! Укажите токен в файле .env"
        )

    request = HTTPXRequest(
        connection_pool_size=8,
        connect_timeout=15.0,
        read_timeout=30.0,
        write_timeout=20.0,
        pool_timeout=10.0,
        http_version="1.1",
    )

    application = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .request(request)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # 1. Основные команды бота
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("settings", cmd_settings))
    application.add_handler(CommandHandler("calendar", export_calendar_handler))
    application.add_handler(CommandHandler("sync", cmd_sync))
    application.add_handler(CommandHandler("bells", cmd_bells))

    # Быстрые команды расписания (для личных и групповых чатов)
    application.add_handler(CommandHandler("now", cmd_now))
    application.add_handler(CommandHandler("today", cmd_today))
    application.add_handler(CommandHandler("tomorrow", cmd_tomorrow))
    application.add_handler(CommandHandler("week", cmd_week))

    # Команды администратора
    application.add_handler(CommandHandler("stats", cmd_stats))
    application.add_handler(CommandHandler("broadcast", cmd_broadcast))

    # 2. Обработка текстовых кнопок главного меню
    application.add_handler(
        MessageHandler(
            filters.Regex("^(⚙️ Настройки|Настройки)$"),
            cmd_settings,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.Regex("^(🔔 Звонки|Звонки)$"),
            cmd_bells,
        )
    )
    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_text_command,
        )
    )

    # 3. Инлайн-кнопки
    application.add_handler(
        CallbackQueryHandler(
            week_callback_handler,
            pattern="^(show_day_|switch_week_|full_week_)",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            settings_callback_handler,
            pattern="^(toggle_notif_|settings_|set_subgroup_)",
        )
    )
    application.add_handler(
        CallbackQueryHandler(
            export_calendar_handler,
            pattern="^export_ics$",
        )
    )

    # 4. Глобальный обработчик ошибок
    application.add_error_handler(error_handler)

    return application


def main() -> None:
    """Точка входа запуска бота."""
    setup_logging()
    logger.info("Запуск Telegram-бота расписания АмГУ 2.0...")

    app = create_application()
    print("Бот успешно запущен в режиме polling. Нажмите Ctrl+C для остановки.")
    app.run_polling()
