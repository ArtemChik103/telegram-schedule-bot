import logging
import asyncio
from datetime import datetime, timedelta, time
from telegram.constants import ParseMode
from telegram.error import Forbidden
from telegram.ext import CallbackContext, Application
from src.config import TIMEZONE, GROUP_ID, GROUP_NAME
from src.database.db import db
from src.api.client import api_client
from src.services.schedule_service import (
    format_day_schedule,
    get_lessons_for_day,
    get_week_type,
    calculate_schedule_hash,
    compute_schedule_diff,
)

logger = logging.getLogger(__name__)


async def send_safe_message(
    bot, chat_id: int, text: str, parse_mode: str = ParseMode.HTML
) -> bool:
    """
    Безопасная отправка сообщения с троттлингом и обработкой блокировки бота.
    Возвращает True в случае успеха, False при ошибке/блокировке.
    """
    try:
        await bot.send_message(chat_id=chat_id, text=text, parse_mode=parse_mode)
        # Троттлинг: пауза 40 мс предотвращает превышение лимита в 30 сообщений/сек в Telegram API
        await asyncio.sleep(0.04)
        return True
    except Forbidden:
        logger.info(f"Пользователь {chat_id} заблокировал бота. Отключаем рассылки.")
        await db.mark_user_blocked(chat_id)
        return False
    except Exception as e:
        logger.warning(f"Не удалось отправить сообщение {chat_id}: {e}")
        return False


async def send_morning_digest(context: CallbackContext) -> None:
    """Утренняя рассылка расписания на сегодня (в 07:30)."""
    try:
        users = await db.get_users_for_morning_digest()
        if not users:
            return

        today = datetime.now(TIMEZONE).date()
        schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
        weekday = today.isoweekday()
        week_type = get_week_type(schedule_data, today)

        for user in users:
            user_id = user["user_id"]
            subgroup = user.get("subgroup", 0)
            notify_only_lessons = user.get("notify_only_with_lessons", 1)

            lessons = get_lessons_for_day(schedule_data, weekday, week_type, subgroup)
            # Если включена опция «не будить в дни без пар» и пар нет — пропускаем
            if notify_only_lessons and not lessons:
                continue

            text = "🌅 <b>Доброе утро! Расписание на сегодня:</b>\n\n"
            text += format_day_schedule(schedule_data, today, subgroup=subgroup)

            await send_safe_message(context.bot, user_id, text)

    except Exception as e:
        logger.error(f"Ошибка в send_morning_digest: {e}", exc_info=True)


async def send_evening_digest(context: CallbackContext) -> None:
    """Вечерняя рассылка расписания на завтра (в 20:00)."""
    try:
        users = await db.get_users_for_evening_digest()
        if not users:
            return

        tomorrow = datetime.now(TIMEZONE).date() + timedelta(days=1)
        schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
        tomorrow_weekday = tomorrow.isoweekday()
        week_type = get_week_type(schedule_data, tomorrow)

        for user in users:
            user_id = user["user_id"]
            subgroup = user.get("subgroup", 0)
            notify_only_lessons = user.get("notify_only_with_lessons", 1)

            lessons = get_lessons_for_day(
                schedule_data, tomorrow_weekday, week_type, subgroup
            )
            # Если завтра нет пар и включен тихий режим — пропускаем
            if notify_only_lessons and not lessons:
                continue

            text = "🌙 <b>Расписание на завтра:</b>\n\n"
            text += format_day_schedule(schedule_data, tomorrow, subgroup=subgroup)

            await send_safe_message(context.bot, user_id, text)

    except Exception as e:
        logger.error(f"Ошибка в send_evening_digest: {e}", exc_info=True)


async def check_schedule_changes_job(context: CallbackContext) -> None:
    """
    Периодическая фоновая проверка изменений в расписании (Schedule Diff).
    При обнаружении изменений автоматически оповещает активных студентов группы.
    """
    try:
        group_id = GROUP_ID
        fresh_data, is_fallback = await api_client.get_group_schedule(
            group_id, force_refresh=True
        )
        if not fresh_data or is_fallback:
            return

        new_hash = calculate_schedule_hash(fresh_data)
        snapshot = await db.get_schedule_snapshot(group_id)

        if snapshot is None:
            # Инициализация первого слепка
            await db.save_schedule_snapshot(group_id, new_hash, fresh_data)
            return

        old_hash, old_data = snapshot
        if new_hash == old_hash:
            return

        # Найдено изменение в расписании!
        diffs = compute_schedule_diff(old_data, fresh_data)
        await db.save_schedule_snapshot(group_id, new_hash, fresh_data)

        if not diffs:
            return

        logger.info(
            f"⚡ Обнаружено {len(diffs)} изменений в расписании группы {group_id}!"
        )
        users = await db.get_all_active_users()
        if not users:
            return

        diff_text = (
            f"⚡ <b>Внимание! Изменение в расписании {GROUP_NAME}!</b>\n\n"
            + "\n\n".join(diffs[:8])
            + "\n\n<i>Актуальное расписание доступно в меню бота 👇</i>"
        )

        for user in users:
            await send_safe_message(context.bot, user["user_id"], diff_text)

    except Exception as e:
        logger.error(f"Ошибка в check_schedule_changes_job: {e}", exc_info=True)


def setup_scheduled_jobs(application: Application) -> None:
    """Регистрирует фоновые задачи рассылки и проверки изменений в JobQueue."""
    job_queue = application.job_queue
    if job_queue is None:
        logger.warning("JobQueue недоступен. Рассылки не будут работать.")
        return

    # Утренний дайджест в 07:30 по времени Благовещенска (UTC+9)
    job_queue.run_daily(
        send_morning_digest,
        time=time(7, 30, tzinfo=TIMEZONE),
        name="morning_digest",
    )

    # Вечерний дайджест в 20:00 по времени Благовещенска (UTC+9)
    job_queue.run_daily(
        send_evening_digest,
        time=time(20, 0, tzinfo=TIMEZONE),
        name="evening_digest",
    )

    # Фоновая проверка изменений расписания (каждый 1 час, первая проверка через 5 минут после старта)
    job_queue.run_repeating(
        check_schedule_changes_job,
        interval=3600,
        first=300,
        name="schedule_diff_checker",
    )

    logger.info("Фоновые задачи JobQueue зарегистрированы (07:30, 20:00, чекер diff).")
