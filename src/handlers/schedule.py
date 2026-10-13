import logging
from datetime import datetime, timedelta
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut, NetworkError
from telegram.ext import CallbackContext
from src.config import TIMEZONE, GROUP_ID
from src.database.db import db
from src.api.client import api_client
from src.services.schedule_service import (
    get_current_status,
    format_day_schedule,
    format_full_week_schedule,
    format_bell_schedule,
)
from src.keyboards.markups import get_week_inline_keyboard

logger = logging.getLogger(__name__)


async def cmd_now(update: Update, context: CallbackContext) -> None:
    """Команда /now: статус текущей пары."""
    if not update.effective_user or not update.message:
        return
    user = await db.get_user(update.effective_user.id)
    subgroup = user.get("subgroup", 0) if user else 0
    schedule_data, is_fallback = await api_client.get_group_schedule(GROUP_ID)
    fallback_note = (
        "⚠️ <i>Сервер АмГУ недоступен (кэш).</i>\n\n" if is_fallback else ""
    )
    msg = get_current_status(schedule_data, subgroup=subgroup)
    await update.message.reply_text(fallback_note + msg, parse_mode=ParseMode.HTML)


async def cmd_today(update: Update, context: CallbackContext) -> None:
    """Команда /today: расписание на сегодня."""
    if not update.effective_user or not update.message:
        return
    user = await db.get_user(update.effective_user.id)
    subgroup = user.get("subgroup", 0) if user else 0
    schedule_data, is_fallback = await api_client.get_group_schedule(GROUP_ID)
    fallback_note = (
        "⚠️ <i>Сервер АмГУ недоступен (кэш).</i>\n\n" if is_fallback else ""
    )
    today = datetime.now(TIMEZONE).date()
    msg = format_day_schedule(schedule_data, today, subgroup=subgroup)
    await update.message.reply_text(fallback_note + msg, parse_mode=ParseMode.HTML)


async def cmd_tomorrow(update: Update, context: CallbackContext) -> None:
    """Команда /tomorrow: расписание на завтра."""
    if not update.effective_user or not update.message:
        return
    user = await db.get_user(update.effective_user.id)
    subgroup = user.get("subgroup", 0) if user else 0
    schedule_data, is_fallback = await api_client.get_group_schedule(GROUP_ID)
    fallback_note = (
        "⚠️ <i>Сервер АмГУ недоступен (кэш).</i>\n\n" if is_fallback else ""
    )
    tomorrow = datetime.now(TIMEZONE).date() + timedelta(days=1)
    msg = format_day_schedule(schedule_data, tomorrow, subgroup=subgroup)
    await update.message.reply_text(fallback_note + msg, parse_mode=ParseMode.HTML)


async def cmd_week(update: Update, context: CallbackContext) -> None:
    """Команда /week: интерактивное меню недели."""
    if not update.effective_user or not update.message:
        return
    user = await db.get_user(update.effective_user.id)
    subgroup = user.get("subgroup", 0) if user else 0
    schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
    await send_week_menu(update, schedule_data, is_next_week=False, subgroup=subgroup)


async def handle_text_command(update: Update, context: CallbackContext) -> None:
    """Обработчик текстовых кнопок главного меню."""
    if not update.message or not update.message.text or not update.effective_user:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id

    # Обновляем профиль пользователя в БД
    user_data = await db.register_or_update_user(
        user_id=user_id,
        username=update.effective_user.username,
        first_name=update.effective_user.first_name,
    )
    subgroup = user_data.get("subgroup", 0)

    # Получаем расписание
    schedule_data, is_fallback = await api_client.get_group_schedule(GROUP_ID)
    fallback_note = (
        "⚠️ <i>Сервер АмГУ недоступен. Показана сохраненная копия.</i>\n\n"
        if is_fallback
        else ""
    )

    today = datetime.now(TIMEZONE).date()

    if text in ("🔴 Сейчас", "Сейчас"):
        msg = get_current_status(schedule_data, subgroup=subgroup)
        await update.message.reply_text(
            fallback_note + msg,
            parse_mode=ParseMode.HTML,
        )

    elif text in ("📅 На сегодня", "На сегодня"):
        msg = format_day_schedule(schedule_data, today, subgroup=subgroup)
        await update.message.reply_text(
            fallback_note + msg,
            parse_mode=ParseMode.HTML,
        )

    elif text in ("➡️ На завтра", "На завтра"):
        tomorrow = today + timedelta(days=1)
        msg = format_day_schedule(schedule_data, tomorrow, subgroup=subgroup)
        await update.message.reply_text(
            fallback_note + msg,
            parse_mode=ParseMode.HTML,
        )

    elif text in ("🗓 Эта неделя", "Эта неделя"):
        await send_week_menu(update, schedule_data, is_next_week=False, subgroup=subgroup)

    elif text in ("⏭ След. неделя", "Следующая неделя"):
        await send_week_menu(update, schedule_data, is_next_week=True, subgroup=subgroup)

    elif text in ("🔔 Звонки", "Звонки"):
        msg = format_bell_schedule(schedule_data)
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def send_week_menu(
    update: Update,
    schedule_data: dict | None,
    is_next_week: bool,
    subgroup: int = 0,
) -> None:
    """Отправляет интерактивное меню недели с кнопками по дням."""
    today = datetime.now(TIMEZONE).date()
    today_weekday = today.isoweekday()

    if is_next_week:
        # Для следующей недели по умолчанию показываем понедельник
        active_day = 1
        days_to_next_monday = 7 - today_weekday + 1
        target_date = today + timedelta(days=days_to_next_monday)
    else:
        # Для текущей недели по умолчанию показываем сегодня (если воскресенье — понедельник)
        active_day = today_weekday if today_weekday <= 6 else 1
        current_monday = today - timedelta(days=today_weekday - 1)
        target_date = current_monday + timedelta(days=active_day - 1)

    text = format_day_schedule(schedule_data, target_date, subgroup=subgroup)
    markup = get_week_inline_keyboard(is_next_week=is_next_week, active_day=active_day)

    await update.message.reply_text(
        text,
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
    )


def split_telegram_message(text: str, max_chunk_size: int = 3900) -> list[str]:
    """Разбивает длинный HTML-текст на части по абзацам или разделителям во избежание лимита в 4096 символов."""
    if len(text) <= max_chunk_size:
        return [text]

    chunks = []
    separator = "\n\n━━━━━━━━━━━━━━━━━━━━━\n\n"
    if separator in text:
        blocks = text.split(separator)
        current_chunk = ""
        for block in blocks:
            piece = block if not current_chunk else separator + block
            if len(current_chunk) + len(piece) <= max_chunk_size:
                current_chunk += piece
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                if len(block) > max_chunk_size:
                    sub = split_telegram_message(block, max_chunk_size)
                    chunks.extend(sub[:-1])
                    current_chunk = sub[-1]
                else:
                    current_chunk = block
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    if "\n\n" in text:
        paragraphs = text.split("\n\n")
        current_chunk = ""
        for para in paragraphs:
            piece = para if not current_chunk else "\n\n" + para
            if len(current_chunk) + len(piece) <= max_chunk_size:
                current_chunk += piece
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                if len(para) > max_chunk_size:
                    sub = split_telegram_message(para, max_chunk_size)
                    chunks.extend(sub[:-1])
                    current_chunk = sub[-1]
                else:
                    current_chunk = para
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    if "\n" in text:
        lines = text.split("\n")
        current_chunk = ""
        for line in lines:
            piece = line if not current_chunk else "\n" + line
            if len(current_chunk) + len(piece) <= max_chunk_size:
                current_chunk += piece
            else:
                if current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = ""
                if len(line) > max_chunk_size:
                    chunks.extend([line[i:i + max_chunk_size] for i in range(0, len(line), max_chunk_size)])
                else:
                    current_chunk = line
        if current_chunk:
            chunks.append(current_chunk)
        return chunks

    return [text[i:i + max_chunk_size] for i in range(0, len(text), max_chunk_size)]


async def week_callback_handler(update: Update, context: CallbackContext) -> None:
    """Обработчик интерактивных кнопок навигации по неделе."""
    query = update.callback_query
    if not query or not query.data or not update.effective_user:
        return

    try:
        await query.answer()
    except (BadRequest, TimedOut, NetworkError):
        pass

    data = query.data
    user = await db.get_user(update.effective_user.id)
    subgroup = user.get("subgroup", 0) if user else 0

    schedule_data, is_fallback = await api_client.get_group_schedule(GROUP_ID)
    fallback_note = (
        "⚠️ <i>Сервер АмГУ недоступен (кэш).</i>\n\n" if is_fallback else ""
    )

    today = datetime.now(TIMEZONE).date()
    today_weekday = today.isoweekday()
    current_monday = today - timedelta(days=today_weekday - 1)

    # 1. Показ конкретного дня недели
    if data.startswith("show_day_"):
        parts = data.split("_")
        is_next = parts[2] == "next"
        day_num = int(parts[3])

        base_monday = current_monday + timedelta(days=7) if is_next else current_monday
        target_date = base_monday + timedelta(days=day_num - 1)

        msg_text = fallback_note + format_day_schedule(
            schedule_data, target_date, subgroup=subgroup
        )
        markup = get_week_inline_keyboard(is_next_week=is_next, active_day=day_num)

        try:
            await query.edit_message_text(
                text=msg_text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
        except (TimedOut, NetworkError) as e:
            logger.warning(f"Сетевой сбой при обновлении дня недели: {e}")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка при edit_message_text: {e}")

    # 2. Переключение между текущей и следующей неделей
    elif data.startswith("switch_week_"):
        is_next = data == "switch_week_next"
        base_monday = current_monday + timedelta(days=7) if is_next else current_monday
        active_day = 1
        target_date = base_monday

        msg_text = fallback_note + format_day_schedule(
            schedule_data, target_date, subgroup=subgroup
        )
        markup = get_week_inline_keyboard(is_next_week=is_next, active_day=active_day)

        try:
            await query.edit_message_text(
                text=msg_text,
                reply_markup=markup,
                parse_mode=ParseMode.HTML,
            )
        except (TimedOut, NetworkError) as e:
            logger.warning(f"Сетевой сбой при переключении недели: {e}")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка при switch_week: {e}")

    # 3. Просмотр всей недели целиком с защитой от превышения лимита 4096 символов
    elif data.startswith("full_week_"):
        is_next = "next" in data
        full_text = fallback_note + format_full_week_schedule(
            schedule_data, is_next_week=is_next, subgroup=subgroup
        )
        markup = get_week_inline_keyboard(is_next_week=is_next, active_day=None)
        chunks = split_telegram_message(full_text, max_chunk_size=3900)

        try:
            if len(chunks) == 1:
                await query.edit_message_text(
                    text=chunks[0],
                    reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                )
            else:
                await query.edit_message_text(
                    text=chunks[0],
                    parse_mode=ParseMode.HTML,
                )
                chat_id = query.message.chat_id if query.message else update.effective_chat.id
                for chunk in chunks[1:-1]:
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=chunk,
                        parse_mode=ParseMode.HTML,
                    )
                await context.bot.send_message(
                    chat_id=chat_id,
                    text=chunks[-1],
                    reply_markup=markup,
                    parse_mode=ParseMode.HTML,
                )
        except (TimedOut, NetworkError) as e:
            logger.warning(f"Сетевой сбой при показе полной недели: {e}")
        except BadRequest as e:
            if "Message is not modified" not in str(e):
                logger.warning(f"Ошибка при full_week: {e}")
