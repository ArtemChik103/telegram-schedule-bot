import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import CallbackContext
from src.config import TIMEZONE, WEEKDAY_NAMES
from src.api.client import api_client
from src.services.schedule_service import (
    search_teachers,
    format_teacher_day_schedule,
    get_teacher_current_status,
)
from src.keyboards.markups import (
    get_teachers_inline_keyboard,
    get_teacher_schedule_keyboard,
)

logger = logging.getLogger(__name__)


async def cmd_teacher(update: Update, context: CallbackContext) -> None:
    """Обработчик поиска преподавателя и его расписания."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    query = ""

    # Если вызов через команду /teacher <фамилия>
    if text.startswith("/"):
        parts = text.split(maxsplit=1)
        if len(parts) > 1:
            query = parts[1].strip()
    # Если нажата кнопка меню
    elif text not in ("👨‍🏫 Преподаватель", "Преподаватель"):
        query = text

    if not query:
        prompt_text = (
            "👨‍🏫 <b>Поиск расписания преподавателя:</b>\n\n"
            "Отправьте команду с фамилией преподавателя:\n"
            "<code>/teacher Фамилия</code>\n\n"
            "<i>Примеры:</i>\n"
            "• <code>/teacher Рябова</code>\n"
            "• <code>/teacher Иванов</code>"
        )
        await update.message.reply_text(prompt_text, parse_mode=ParseMode.HTML)
        return

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

    # Если найдено несколько совпадений — предлагаем выбрать
    if len(matched) > 1:
        markup = get_teachers_inline_keyboard(matched)
        await update.message.reply_text(
            f"🔍 По запросу «<b>{query}</b>» найдено несколько преподавателей.\n"
            f"Выберите нужного из списка ниже 👇",
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )
        return

    # Если найден ровно один преподаватель
    teacher = matched[0]
    await send_teacher_schedule_card(update, teacher["id"])


async def send_teacher_schedule_card(update: Update, teacher_id: int) -> None:
    """Загружает и отправляет карточку расписания преподавателя."""
    schedule_data = await api_client.get_teacher_schedule(teacher_id)
    if not schedule_data:
        msg = "⚠️ Не удалось загрузить расписание выбранного преподавателя."
        if update.message:
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    now_dt = datetime.now(TIMEZONE)
    today = now_dt.date()

    status_text = get_teacher_current_status(schedule_data)
    today_schedule = format_teacher_day_schedule(schedule_data, today)

    full_text = f"{status_text}\n\n━━━━━━━━━━━━━━━━━━━━━\n\n{today_schedule}"
    markup = get_teacher_schedule_keyboard(teacher_id)

    if update.message:
        await update.message.reply_text(full_text, reply_markup=markup, parse_mode=ParseMode.HTML)
    elif update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                full_text, reply_markup=markup, parse_mode=ParseMode.HTML
            )
        except BadRequest:
            pass


async def teacher_callback_handler(update: Update, context: CallbackContext) -> None:
    """Обработчик инлайн-кнопок преподавателей."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()
    data = query.data

    if data.startswith("teacher_select_"):
        teacher_id = int(data.split("_")[-1])
        await send_teacher_schedule_card(update, teacher_id)

    elif data.startswith("teacher_status_"):
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
                reply_markup=get_teacher_schedule_keyboard(teacher_id),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest:
            pass

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
                reply_markup=get_teacher_schedule_keyboard(teacher_id),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest:
            pass

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
                reply_markup=get_teacher_schedule_keyboard(teacher_id),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest:
            pass

    elif data.startswith("teacher_week_"):
        teacher_id = int(data.split("_")[-1])
        schedule_data = await api_client.get_teacher_schedule(teacher_id)
        if not schedule_data:
            return
        today = datetime.now(TIMEZONE).date()
        current_monday = today - timedelta(days=today.isoweekday() - 1)
        teacher_info = schedule_data.get("teacher", {})
        teacher_name = teacher_info.get("name", "Преподаватель")

        parts = [f"👨‍🏫 <b>Расписание на неделю: {teacher_name}</b>\n"]
        for day_offset in range(6):  # ПН..СБ
            day_date = current_monday + timedelta(days=day_offset)
            day_text = format_teacher_day_schedule(schedule_data, day_date)
            parts.append(day_text)
            parts.append("─────────────────────")

        full_text = "\n".join(parts[:-1])  # убираем последний разделитель
        try:
            await query.edit_message_text(
                full_text,
                reply_markup=get_teacher_schedule_keyboard(teacher_id),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest:
            pass
