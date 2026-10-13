import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut, NetworkError
from telegram.ext import CallbackContext
from src.database.db import db
from src.keyboards.markups import (
    get_settings_inline_keyboard,
    get_subgroup_select_keyboard,
    get_digest_time_keyboard,
)

logger = logging.getLogger(__name__)


async def cmd_settings(update: Update, context: CallbackContext) -> None:
    """Отображает меню настроек пользователя или группы."""
    if not update.effective_chat:
        return

    is_group = update.effective_chat.type in ("group", "supergroup")
    target_id = (
        update.effective_chat.id
        if is_group
        else (update.effective_user.id if update.effective_user else update.effective_chat.id)
    )
    target_name = (
        update.effective_chat.title
        if is_group
        else (update.effective_user.first_name if update.effective_user else "Пользователь")
    )
    target_username = (
        update.effective_chat.username
        if is_group
        else (update.effective_user.username if update.effective_user else None)
    )

    user = await db.get_user(target_id)
    if not user:
        user = await db.register_or_update_user(
            user_id=target_id,
            username=target_username,
            first_name=target_name,
        )

    title_label = f"беседы «{target_name}»" if is_group else "профиля"
    text = (
        f"⚙️ <b>Настройки {title_label}:</b>\n\n"
        "• <b>Подгруппа</b> — фильтрует расписание (для беседы обычно «Вся группа»).\n"
        "• <b>Утренний дайджест</b> — расписание на сегодня прямо сюда в выбранное время (кнопка ⏰).\n"
        "• <b>Вечерний дайджест</b> — расписание на завтра прямо сюда в выбранное время (кнопка ⏰).\n"
        "• <b>Напоминание до пары</b> — push за 10-15 минут с аудиторией и предупреждением о переходе в другой корпус.\n"
        "• <b>Без пар не будить</b> — отключает утреннюю рассылку в дни, когда нет пар (выходные, праздники).\n"
        "• <b>Экспорт в календарь</b> — формирует файл <code>.ics</code> для Google Calendar / Apple Calendar."
    )

    markup = get_settings_inline_keyboard(user)

    if update.message:
        await update.message.reply_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML
        )
    elif update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=markup, parse_mode=ParseMode.HTML
        )


async def settings_callback_handler(update: Update, context: CallbackContext) -> None:
    """Обработчик callback-кнопок меню настроек."""
    query = update.callback_query
    if not query or not query.data or not update.effective_chat:
        return

    is_group = update.effective_chat.type in ("group", "supergroup")
    target_id = (
        update.effective_chat.id
        if is_group
        else (update.effective_user.id if update.effective_user else update.effective_chat.id)
    )
    target_desc = "в беседу" if is_group else ""
    data = query.data

    async def _safe_answer(text: str | None = None) -> None:
        try:
            if text:
                await query.answer(text)
            else:
                await query.answer()
        except (BadRequest, TimedOut, NetworkError):
            pass

    # Переключение утреннего дайджеста
    if data == "toggle_notif_morning":
        new_state = await db.toggle_notification(target_id, "morning")
        user = await db.get_user(target_id)
        m_time = user.get("notify_morning_time", "07:30") if user else "07:30"
        status_str = f"включен ({m_time}) {target_desc}".strip() if new_state else f"выключен {target_desc}".strip()
        await _safe_answer(f"Утренний дайджест {status_str}!")
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_settings_inline_keyboard(user)
            )
        except (BadRequest, TimedOut, NetworkError):
            pass

    # Переключение вечернего дайджеста
    elif data == "toggle_notif_evening":
        new_state = await db.toggle_notification(target_id, "evening")
        user = await db.get_user(target_id)
        e_time = user.get("notify_evening_time", "20:00") if user else "20:00"
        status_str = f"включен ({e_time}) {target_desc}".strip() if new_state else f"выключен {target_desc}".strip()
        await _safe_answer(f"Вечерний дайджест {status_str}!")
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_settings_inline_keyboard(user)
            )
        except (BadRequest, TimedOut, NetworkError):
            pass

    # Переключение уведомления перед парой (за 10-15 мин)
    elif data == "toggle_notif_lesson":
        new_state = await db.toggle_notification(target_id, "lesson")
        status_str = f"включены (за 15 мин) {target_desc}".strip() if new_state else f"выключены {target_desc}".strip()
        await _safe_answer(f"Напоминания перед парами {status_str}!")
        user = await db.get_user(target_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_settings_inline_keyboard(user)
            )
        except (BadRequest, TimedOut, NetworkError):
            pass

    # Выбор времени утреннего дайджеста
    elif data == "pick_time_morning":
        await _safe_answer()
        await query.edit_message_text(
            "🌅 <b>Выберите время утреннего дайджеста (расписание на сегодня):</b>",
            reply_markup=get_digest_time_keyboard("morning"),
            parse_mode=ParseMode.HTML,
        )

    # Выбор времени вечернего дайджеста
    elif data == "pick_time_evening":
        await _safe_answer()
        await query.edit_message_text(
            "🌙 <b>Выберите время вечернего дайджеста (расписание на завтра):</b>",
            reply_markup=get_digest_time_keyboard("evening"),
            parse_mode=ParseMode.HTML,
        )

    # Установка конкретного времени дайджеста
    elif data.startswith("set_time_"):
        parts = data.split("_")
        digest_type = parts[2]
        chosen_time = parts[3]
        await db.update_user_digest_time(target_id, digest_type, chosen_time)
        t_label = "Утренний дайджест" if digest_type == "morning" else "Вечерний дайджест"
        await _safe_answer(f"{t_label} перенесен на {chosen_time}!")
        user = await db.get_user(target_id)
        await cmd_settings(update, context)

    # Переключение опции «Без пар не будить»
    elif data == "toggle_notif_only_lessons":
        new_state = await db.toggle_notification(target_id, "only_lessons")
        status_str = "включен (тишина)" if new_state else "выключен"
        await _safe_answer(f"Режим без пар: {status_str}!")
        user = await db.get_user(target_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_settings_inline_keyboard(user)
            )
        except (BadRequest, TimedOut, NetworkError):
            pass

    # Открытие меню выбора подгруппы
    elif data == "settings_subgroup":
        await _safe_answer()
        sub_desc = "для этой беседы" if is_group else "вашу"
        text = (
            f"👥 <b>Выберите {sub_desc} подгруппу:</b>\n\n"
            "• <i>Вся группа</i> — отображаются все пары без фильтрации.\n"
            "• <i>1-я / 2-я подгруппа</i> — отображаются только общие пары и пары выбранной подгруппы."
        )
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=get_subgroup_select_keyboard(),
                parse_mode=ParseMode.HTML,
            )
        except (BadRequest, TimedOut, NetworkError):
            pass

    # Установка выбранной подгруппы (0, 1 или 2)
    elif data.startswith("set_subgroup_"):
        sub_num = int(data.split("_")[-1])
        await db.update_user_subgroup(target_id, sub_num)
        sub_label = "Вся группа" if sub_num == 0 else f"{sub_num}-я подгруппа"
        await _safe_answer(f"Выбрана: {sub_label}")
        # Возврат в главное меню настроек
        user = await db.get_user(target_id)
        await cmd_settings(update, context)

    # Кнопка «Назад» в настройки
    elif data == "settings_back":
        await _safe_answer()
        user = await db.get_user(target_id)
        await cmd_settings(update, context)
