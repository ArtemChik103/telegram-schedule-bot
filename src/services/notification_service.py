import html
import logging
import asyncio
from datetime import datetime, timedelta, time
from telegram.constants import ParseMode
from telegram.error import Forbidden
from telegram.ext import CallbackContext, Application
from src.config import TIMEZONE, GROUP_ID, GROUP_NAME, LESSON_REMINDER_MINUTES
from src.database.db import db
from src.api.client import api_client
from src.services.schedule_service import (
    format_day_schedule,
    get_lessons_for_day,
    get_week_type,
    get_bell_schedule,
    get_bell_schedule_str,
    extract_building,
    format_building_label,
    calculate_schedule_hash,
    compute_schedule_diff,
)

logger = logging.getLogger(__name__)

# Память отправленных дайджестов: {(user_id, date_str, 'morning'/'evening')}
_sent_digests: set[tuple[int, str, str]] = set()

# Память отправленных напоминаний о парах: {(user_id, date_str, lesson_num)}
_sent_lesson_reminders: set[tuple[int, str, int]] = set()


def _cleanup_old_cache(current_date_str: str) -> None:
    """Удаляет из памяти записи за прошедшие даты во избежание утечки памяти."""
    global _sent_digests, _sent_lesson_reminders
    if len(_sent_digests) > 500:
        _sent_digests = {x for x in _sent_digests if x[1] == current_date_str}
    if len(_sent_lesson_reminders) > 500:
        _sent_lesson_reminders = {x for x in _sent_lesson_reminders if x[1] == current_date_str}


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


async def send_morning_digest(context: CallbackContext, users: list[dict] | None = None) -> None:
    """Утренняя рассылка расписания на сегодня."""
    try:
        if users is None:
            users = await db.get_users_for_morning_digest()
        if not users:
            return

        today = datetime.now(TIMEZONE).date()
        today_str = str(today)
        _cleanup_old_cache(today_str)
        schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
        weekday = today.isoweekday()
        week_type = get_week_type(schedule_data, today)

        for user in users:
            user_id = user["user_id"]
            if (user_id, today_str, "morning") in _sent_digests:
                continue

            subgroup = user.get("subgroup", 0)
            notify_only_lessons = user.get("notify_only_with_lessons", 1)

            lessons = get_lessons_for_day(schedule_data, weekday, week_type, subgroup)
            # Если включена опция «не будить в дни без пар» и пар нет — пропускаем
            if notify_only_lessons and not lessons:
                _sent_digests.add((user_id, today_str, "morning"))
                continue

            is_group = user_id < 0
            greeting = (
                "🌅 <b>Доброе утро, группа! Расписание на сегодня:</b>\n\n"
                if is_group
                else "🌅 <b>Доброе утро! Расписание на сегодня:</b>\n\n"
            )
            text = greeting + format_day_schedule(schedule_data, today, subgroup=subgroup)

            sent = await send_safe_message(context.bot, user_id, text)
            if sent:
                _sent_digests.add((user_id, today_str, "morning"))

    except Exception as e:
        logger.error(f"Ошибка в send_morning_digest: {e}", exc_info=True)


async def send_evening_digest(context: CallbackContext, users: list[dict] | None = None) -> None:
    """Вечерняя рассылка расписания на завтра."""
    try:
        if users is None:
            users = await db.get_users_for_evening_digest()
        if not users:
            return

        today = datetime.now(TIMEZONE).date()
        today_str = str(today)
        _cleanup_old_cache(today_str)
        tomorrow = today + timedelta(days=1)
        schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
        tomorrow_weekday = tomorrow.isoweekday()
        week_type = get_week_type(schedule_data, tomorrow)

        for user in users:
            user_id = user["user_id"]
            if (user_id, today_str, "evening") in _sent_digests:
                continue

            subgroup = user.get("subgroup", 0)
            notify_only_lessons = user.get("notify_only_with_lessons", 1)

            lessons = get_lessons_for_day(
                schedule_data, tomorrow_weekday, week_type, subgroup
            )
            # Если завтра нет пар и включен тихий режим — пропускаем
            if notify_only_lessons and not lessons:
                _sent_digests.add((user_id, today_str, "evening"))
                continue

            is_group = user_id < 0
            greeting = (
                "🌙 <b>Расписание группы на завтра:</b>\n\n"
                if is_group
                else "🌙 <b>Расписание на завтра:</b>\n\n"
            )
            text = greeting + format_day_schedule(schedule_data, tomorrow, subgroup=subgroup)

            sent = await send_safe_message(context.bot, user_id, text)
            if sent:
                _sent_digests.add((user_id, today_str, "evening"))

    except Exception as e:
        logger.error(f"Ошибка в send_evening_digest: {e}", exc_info=True)


async def check_and_send_scheduled_digests_job(context: CallbackContext) -> None:
    """
    Поминутный диспетчер персональных утренних и вечерних дайджестов.
    Проверяет пользователей, чье настроенное время (notify_morning_time / notify_evening_time)
    совпадает с текущей минутой.
    """
    try:
        now_dt = datetime.now(TIMEZONE)
        current_hm = now_dt.strftime("%H:%M")
        today = now_dt.date()
        today_str = str(today)

        _cleanup_old_cache(today_str)

        # 1. Персональные утренние дайджесты на текущую минуту
        morning_users = await db.get_users_for_morning_digest(time_str=current_hm)
        to_send_morning = [
            u for u in morning_users
            if (u["user_id"], today_str, "morning") not in _sent_digests
        ]
        if to_send_morning:
            schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
            weekday = today.isoweekday()
            week_type = get_week_type(schedule_data, today)

            for user in to_send_morning:
                u_id = user["user_id"]
                subgroup = user.get("subgroup", 0)
                notify_only_lessons = user.get("notify_only_with_lessons", 1)

                lessons = get_lessons_for_day(schedule_data, weekday, week_type, subgroup)
                if notify_only_lessons and not lessons:
                    _sent_digests.add((u_id, today_str, "morning"))
                    continue

                is_group = u_id < 0
                greeting = (
                    "🌅 <b>Доброе утро, группа! Расписание на сегодня:</b>\n\n"
                    if is_group
                    else "🌅 <b>Доброе утро! Расписание на сегодня:</b>\n\n"
                )
                text = greeting + format_day_schedule(schedule_data, today, subgroup=subgroup)
                sent = await send_safe_message(context.bot, u_id, text)
                if sent:
                    _sent_digests.add((u_id, today_str, "morning"))

        # 2. Персональные вечерние дайджесты на текущую минуту
        evening_users = await db.get_users_for_evening_digest(time_str=current_hm)
        to_send_evening = [
            u for u in evening_users
            if (u["user_id"], today_str, "evening") not in _sent_digests
        ]
        if to_send_evening:
            tomorrow = today + timedelta(days=1)
            tomorrow_weekday = tomorrow.isoweekday()
            schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
            week_type = get_week_type(schedule_data, tomorrow)

            for user in to_send_evening:
                u_id = user["user_id"]
                subgroup = user.get("subgroup", 0)
                notify_only_lessons = user.get("notify_only_with_lessons", 1)

                lessons = get_lessons_for_day(schedule_data, tomorrow_weekday, week_type, subgroup)
                if notify_only_lessons and not lessons:
                    _sent_digests.add((u_id, today_str, "evening"))
                    continue

                is_group = u_id < 0
                greeting = (
                    "🌙 <b>Расписание группы на завтра:</b>\n\n"
                    if is_group
                    else "🌙 <b>Расписание на завтра:</b>\n\n"
                )
                text = greeting + format_day_schedule(schedule_data, tomorrow, subgroup=subgroup)
                sent = await send_safe_message(context.bot, u_id, text)
                if sent:
                    _sent_digests.add((u_id, today_str, "evening"))

    except Exception as e:
        logger.error(f"Ошибка в check_and_send_scheduled_digests_job: {e}", exc_info=True)


async def send_lesson_reminders_job(context: CallbackContext) -> None:
    """
    Поминутная проверка и отправка push-уведомлений за 10-15 минут до начала пары.
    Включает информацию о предмете, времени, аудитории, корпусе и предупреждение о смене корпуса.
    """
    try:
        now_dt = datetime.now(TIMEZONE)
        today = now_dt.date()
        today_str = str(today)
        _cleanup_old_cache(today_str)
        weekday = today.isoweekday()

        if weekday == 7:
            # Воскресенье — пар нет
            return

        users = await db.get_users_for_lesson_reminders()
        if not users:
            return

        schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
        if not schedule_data:
            return

        bells = get_bell_schedule(schedule_data)
        bells_str = get_bell_schedule_str(schedule_data)
        week_type = get_week_type(schedule_data, today)

        for lesson_num, (start_time, _) in bells.items():
            start_dt = datetime.combine(today, start_time, tzinfo=TIMEZONE)
            diff_mins = int((start_dt - now_dt).total_seconds() // 60)

            # Окно предварительного напоминания: за LESSON_REMINDER_MINUTES (по умолчанию 15 мин) до начала
            if 0 < diff_mins <= LESSON_REMINDER_MINUTES:
                for user in users:
                    user_id = user["user_id"]
                    subgroup = user.get("subgroup", 0)
                    cache_key = (user_id, today_str, lesson_num)

                    if cache_key in _sent_lesson_reminders:
                        continue

                    lessons_today = get_lessons_for_day(schedule_data, weekday, week_type, subgroup)
                    matching = [l for l in lessons_today if l.get("lesson") == lesson_num]
                    if not matching:
                        continue

                    lesson = matching[0]
                    subj = html.escape(lesson.get("discipline_str") or "Занятие")
                    raw_room = lesson.get("classroom_str") or "Не указана"
                    room = html.escape(raw_room)
                    teacher = html.escape(lesson.get("person_str") or "Не указан")
                    curr_building = extract_building(raw_room)
                    b_label = f" ({format_building_label(curr_building)})" if curr_building else ""

                    # Проверяем смену корпуса относительно предшествующей пары студента сегодня
                    earlier_lessons = [l for l in lessons_today if l.get("lesson", 0) < lesson_num]
                    building_warning = ""
                    if earlier_lessons and curr_building:
                        prev_lesson = earlier_lessons[-1]
                        prev_building = extract_building(prev_lesson.get("classroom_str"))
                        if prev_building and prev_building.lower() != curr_building.lower():
                            p_name = format_building_label(prev_building)
                            c_name = format_building_label(curr_building)
                            building_warning = (
                                f"\n⚠️ <b>Внимание: смена корпуса!</b>\n"
                                f"Предыдущая пара была в <b>{p_name}</b>, а эта — в <b>{c_name}</b>. "
                                f"Рассчитайте время на дорогу!\n"
                            )

                    stream_with = lesson.get("stream_with")
                    stream_tag = (
                        f"\n👥 <b>Поток с группой:</b> <code>{html.escape(', '.join(stream_with))}</code>"
                        if stream_with
                        else ""
                    )

                    text = (
                        f"🔔 <b>Скоро начнется пара! (через ~{diff_mins} мин)</b>\n\n"
                        f"⏰ <b>{lesson_num}-я пара</b> (<code>{bells_str.get(lesson_num, '')}</code>)\n"
                        f"📚 <b>{subj}</b>\n"
                        f"🚪 Ауд. <b>{room}</b>{b_label}\n"
                        f"🧑‍🏫 {teacher}"
                        f"{stream_tag}\n"
                        f"{building_warning}"
                    )

                    sent = await send_safe_message(context.bot, user_id, text)
                    if sent:
                        _sent_lesson_reminders.add(cache_key)

    except Exception as e:
        logger.error(f"Ошибка в send_lesson_reminders_job: {e}", exc_info=True)


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

    # Поминутный диспетчер персональных утренних и вечерних дайджестов
    job_queue.run_repeating(
        check_and_send_scheduled_digests_job,
        interval=60,
        first=5,
        name="digest_dispatcher",
    )

    # Поминутная проверка напоминаний за 10-15 минут до начала пары
    job_queue.run_repeating(
        send_lesson_reminders_job,
        interval=60,
        first=10,
        name="lesson_reminders",
    )

    # Фоновая проверка изменений расписания (каждые 3 часа, первая проверка через 10 минут после старта)
    job_queue.run_repeating(
        check_schedule_changes_job,
        interval=10800,
        first=600,
        name="schedule_diff_checker",
    )

    logger.info("Фоновые задачи JobQueue зарегистрированы (дайджесты, пуши до пар, чекер diff).")
