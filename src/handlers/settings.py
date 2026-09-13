import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest, TimedOut, NetworkError
from telegram.ext import CallbackContext
from src.database.db import db
from src.keyboards.markups import (
    get_settings_inline_keyboard,
    get_subgroup_select_keyboard,
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
        "• <b>Утренний дайджест (07:30)</b> — бот автоматически присылает расписание на сегодня прямо сюда.\n"
        "• <b>Вечерний дайджест (20:00)</b> — бот присылает расписание на завтра прямо сюда.\n"
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
        status_str = f"включен (07:30) {target_desc}".strip() if new_state else f"выключен {target_desc}".strip()
        await _safe_answer(f"Утренний дайджест {status_str}!")
        user = await db.get_user(target_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_settings_inline_keyboard(user)
            )
        except (BadRequest, TimedOut, NetworkError):
            pass

    # Переключение вечернего дайджеста
    elif data == "toggle_notif_evening":
        new_state = await db.toggle_notification(target_id, "evening")
        status_str = f"включен (20:00) {target_desc}".strip() if new_state else f"выключен {target_desc}".strip()
        await _safe_answer(f"Вечерний дайджест {status_str}!")
        user = await db.get_user(target_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_settings_inline_keyboard(user)
            )
        except (BadRequest, TimedOut, NetworkError):
            pass

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
