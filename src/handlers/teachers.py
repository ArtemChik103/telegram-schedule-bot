import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import CallbackContext
from src.config import TIMEZONE, GROUP_ID
from src.api.client import api_client
from src.services.schedule_service import (
    search_teachers,
    get_group_teachers,
    format_teacher_day_schedule,
    get_teacher_current_status,
)
from src.keyboards.markups import (
    get_teachers_inline_keyboard,
    get_teacher_schedule_keyboard,
    get_teacher_week_keyboard,
)

logger = logging.getLogger(__name__)


async def cmd_teacher(update: Update, context: CallbackContext) -> None:
    """Главный обработчик раздела преподавателей."""
    if not update.message:
        return

    text = (update.message.text or "").strip()
    query = ""

    # Если вызвана команда /teacher или /teachers с параметром
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            query = parts[1].strip()

    # 1. Если параметр не указан (нажата кнопка меню или просто /teachers) — показываем список преподавателей нашей группы
    if not query:
        schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
        teachers = get_group_teachers(schedule_data)

        if not teachers:
            await update.message.reply_text(
                "⚠️ Не удалось загрузить список преподавателей группы ИС231.",
                parse_mode=ParseMode.HTML,
            )
            return

        markup = get_teachers_inline_keyboard(teachers)
        msg_text = (
            "👨‍🏫 <b>Преподаватели группы ИС231:</b>\n\n"
            "Выберите преподавателя, чтобы узнать его расписание или где он находится прямо сейчас 👇"
        )
        await update.message.reply_text(msg_text, reply_markup=markup, parse_mode=ParseMode.HTML)
        return

    # 2. Если передан конкретный запрос (поиск по фамилии)
    teachers = await api_client.get_teachers_list()
    if not teachers:
        await update.message.reply_text(
            "⚠️ Не удалось получить список преподавателей с сервера АмГУ.",
            parse_mode=ParseMode.HTML,
        )
        return

    matched = search_teachers(query, teachers)
    if not matched:
        await update.message.reply_text(
            f"❌ Преподаватель по запросу «<b>{query}</b>» не найден в базе АмГУ.\n"
            f"Проверьте правильность написания фамилии.",
            parse_mode=ParseMode.HTML,
        )
        return

    if len(matched) > 1:
        markup = get_teachers_inline_keyboard(matched)
        await update.message.reply_text(
            f"🔍 По запросу «<b>{query}</b>» найдено несколько преподавателей.\n"
            f"Выберите нужного из списка ниже 👇",
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        return

    await send_teacher_schedule_card(update, matched[0]["id"], active_tab="today")


async def send_teacher_schedule_card(
    update: Update, teacher_id: int, active_tab: str = "today"
) -> None:
    """Загружает и отправляет карточку расписания преподавателя."""
    schedule_data = await api_client.get_teacher_schedule(teacher_id)
    if not schedule_data:
        err_msg = "⚠️ Не удалось загрузить расписание выбранного преподавателя."
        if update.message:
            await update.message.reply_text(err_msg, parse_mode=ParseMode.HTML)
        elif update.callback_query:
            await update.callback_query.message.reply_text(err_msg, parse_mode=ParseMode.HTML)
        return

    now_dt = datetime.now(TIMEZONE)
    today = now_dt.date()

    status_text = get_teacher_current_status(schedule_data)
    today_schedule = format_teacher_day_schedule(schedule_data, today)
    full_text = f"{status_text}\n\n━━━━━━━━━━━━━━━━━━━━━\n\n{today_schedule}"
    markup = get_teacher_schedule_keyboard(teacher_id, active_tab=active_tab)

    if update.message:
        await update.message.reply_text(full_text, reply_markup=markup, parse_mode=ParseMode.HTML)
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                full_text, reply_markup=markup, parse_mode=ParseMode.HTML
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка редактирования сообщения: {e}")


async def teacher_callback_handler(update: Update, context: CallbackContext) -> None:
    """Обработчик инлайн-кнопок преподавателей."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    data = query.data

    # Возврат к общему списку преподавателей нашей группы
    if data == "teacher_list":
        schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
        teachers = get_group_teachers(schedule_data)
        markup = get_teachers_inline_keyboard(teachers)
        msg_text = (
            "👨‍🏫 <b>Преподаватели группы ИС231:</b>\n\n"
            "Выберите преподавателя, чтобы узнать его расписание или где он находится прямо сейчас 👇"
        )
        try:
            await query.edit_message_text(msg_text, reply_markup=markup, parse_mode=ParseMode.HTML)
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка при возврате к списку преподавателей: {e}")
        return

    # Выбор преподавателя из списка
    if data.startswith("teacher_select_"):
        teacher_id = int(data.split("_")[-1])
        await send_teacher_schedule_card(update, teacher_id, active_tab="today")
        return

    # Статус "Где сейчас"
    if data.startswith("teacher_status_"):
        teacher_id = int(data.split("_")[-1])
        schedule_data = await api_client.get_teacher_schedule(teacher_id)
        if not schedule_data:
            return
        status_text = get_teacher_current_status(schedule_data)
        today = datetime.now(TIMEZONE).date()
        today_sched = format_teacher_day_schedule(schedule_data, today)
        full_text = f"{status_text}\n\n━━━━━━━━━━━━━━━━━━━━━\n\n{today_sched}"
        try:
            await query.edit_message_text(
                full_text,
                reply_markup=get_teacher_schedule_keyboard(teacher_id, active_tab="status"),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка редактирования: {e}")

    # Расписание на сегодня
    elif data.startswith("teacher_today_"):
        teacher_id = int(data.split("_")[-1])
        schedule_data = await api_client.get_teacher_schedule(teacher_id)
        if not schedule_data:
            return
        today = datetime.now(TIMEZONE).date()
        text = format_teacher_day_schedule(schedule_data, today)
        try:
            await query.edit_message_text(
                text,
                reply_markup=get_teacher_schedule_keyboard(teacher_id, active_tab="today"),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка редактирования: {e}")

    # Расписание на завтра
    elif data.startswith("teacher_tomorrow_"):
        teacher_id = int(data.split("_")[-1])
        schedule_data = await api_client.get_teacher_schedule(teacher_id)
        if not schedule_data:
            return
        tomorrow = datetime.now(TIMEZONE).date() + timedelta(days=1)
        text = format_teacher_day_schedule(schedule_data, tomorrow)
        try:
            await query.edit_message_text(
                text,
                reply_markup=get_teacher_schedule_keyboard(teacher_id, active_tab="tomorrow"),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка редактирования: {e}")

    # Интерактивное расписание на неделю с кнопками дней
    elif data.startswith("teacher_week_"):
        teacher_id = int(data.split("_")[-1])
        schedule_data = await api_client.get_teacher_schedule(teacher_id)
        if not schedule_data:
            return
        today = datetime.now(TIMEZONE).date()
        iso_day = today.isoweekday()
        active_day = iso_day if iso_day <= 6 else 1

        current_monday = today - timedelta(days=iso_day - 1)
        target_date = current_monday + timedelta(days=active_day - 1)
        text = format_teacher_day_schedule(schedule_data, target_date)

        try:
            await query.edit_message_text(
                text,
                reply_markup=get_teacher_week_keyboard(teacher_id, active_day=active_day),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка редактирования недели преподавателя: {e}")

    # Переключение дня в недельном расписании преподавателя
    elif data.startswith("teacher_day_"):
        parts = data.split("_")
        teacher_id = int(parts[2])
        day_num = int(parts[3])
        schedule_data = await api_client.get_teacher_schedule(teacher_id)
        if not schedule_data:
            return

        today = datetime.now(TIMEZONE).date()
        current_monday = today - timedelta(days=today.isoweekday() - 1)
        target_date = current_monday + timedelta(days=day_num - 1)
        text = format_teacher_day_schedule(schedule_data, target_date)

        try:
            await query.edit_message_text(
                text,
                reply_markup=get_teacher_week_keyboard(teacher_id, active_day=day_num),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка переключения дня преподавателя: {e}")
