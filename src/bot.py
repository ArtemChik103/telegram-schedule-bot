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
from src.handlers.teachers import cmd_teacher, teacher_callback_handler
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


import asyncio
import socket
from typing import Optional, Tuple
from telegram.error import TimedOut, NetworkError
from telegram.request import HTTPXRequest, BaseRequest
from telegram.request._requestdata import RequestData
from telegram._utils.defaultvalue import DefaultValue

# Патч DNS для Telegram API (обход блокировок хостинга/ТСПУ)
_orig_getaddrinfo = socket.getaddrinfo


def _telegram_dns_patch(host, port, family=0, type=0, proto=0, flags=0):
    host_str = (
        host.decode("utf-8", errors="ignore")
        if isinstance(host, bytes)
        else str(host or "")
    )
    if host_str.rstrip(".").lower() == "api.telegram.org":
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("149.154.167.220", port))
        ]
    return _orig_getaddrinfo(host, port, family, type, proto, flags)


socket.getaddrinfo = _telegram_dns_patch


class ResilientHTTPXRequest(HTTPXRequest):
    """
    HTTP-клиент с автоматическими повторными попытками (retries) при кратковременных
    сетевых сбоях и таймаутах Telegram API, устраняющий случайные дропы запросов.
    """

    async def do_request(
        self,
        url: str,
        method: str,
        request_data: Optional[RequestData] = None,
        read_timeout: float | None | DefaultValue = BaseRequest.DEFAULT_NONE,
        write_timeout: float | None | DefaultValue = BaseRequest.DEFAULT_NONE,
        connect_timeout: float | None | DefaultValue = BaseRequest.DEFAULT_NONE,
        pool_timeout: float | None | DefaultValue = BaseRequest.DEFAULT_NONE,
    ) -> Tuple[int, bytes]:
        # Для getUpdates (поллинг) повторы не нужны, так как PTB сам управляет бесконечным циклом опроса
        is_get_updates = url.rstrip("/").endswith("getUpdates")
        max_retries = 0 if is_get_updates else 2

        for attempt in range(max_retries + 1):
            try:
                return await super().do_request(
                    url=url,
                    method=method,
                    request_data=request_data,
                    read_timeout=read_timeout,
                    write_timeout=write_timeout,
                    connect_timeout=connect_timeout,
                    pool_timeout=pool_timeout,
                )
            except (TimedOut, NetworkError) as err:
                if attempt < max_retries and "Pool timeout" not in str(err):
                    backoff = 0.5 * (attempt + 1)
                    logger.warning(
                        f"Временный сетевой сбой Telegram API ({err}). "
                        f"Повтор {attempt + 1}/{max_retries} через {backoff}с..."
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise


def create_application() -> Application:
    """Создает и настраивает экземпляр Telegram Application."""
    if not TELEGRAM_TOKEN or TELEGRAM_TOKEN == "ВАШ_ТОКЕН":
        raise ValueError(
            "TELEGRAM_BOT_TOKEN не задан! Укажите токен в файле .env"
        )

    sock_opts = [(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)]
    if hasattr(socket, "TCP_NODELAY"):
        sock_opts.append((socket.IPPROTO_TCP, socket.TCP_NODELAY, 1))
    if hasattr(socket, "TCP_KEEPIDLE"):
        sock_opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30))
    if hasattr(socket, "TCP_KEEPINTVL"):
        sock_opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10))
    if hasattr(socket, "TCP_KEEPCNT"):
        sock_opts.append((socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3))

    request = ResilientHTTPXRequest(
        connection_pool_size=16,
        connect_timeout=20.0,
        read_timeout=35.0,
        write_timeout=25.0,
        pool_timeout=15.0,
        media_write_timeout=40.0,
        http_version="1.1",
        socket_options=sock_opts,
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
    application.add_handler(CommandHandler(["teacher", "teachers", "prep"], cmd_teacher))

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
            filters.Regex("^(👨‍🏫 Преподаватели|👨‍🏫 Преподаватель|Преподаватели|Преподаватель)$"),
            cmd_teacher,
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
    application.add_handler(
        CallbackQueryHandler(
            teacher_callback_handler,
            pattern="^teacher_",
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
