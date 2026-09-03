import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import CallbackContext
from src.database.db import db
from src.keyboards.markups import (
    get_settings_inline_keyboard,
    get_subgroup_select_keyboard,
)

logger = logging.getLogger(__name__)


async def cmd_settings(update: Update, context: CallbackContext) -> None:
    """Отображает меню настроек пользователя."""
    if not update.effective_user:
        return

    user = await db.get_user(update.effective_user.id)
    if not user:
        user = await db.register_or_update_user(
            user_id=update.effective_user.id,
            username=update.effective_user.username,
            first_name=update.effective_user.first_name,
        )

    text = (
        "⚙️ <b>Настройки профиля:</b>\n\n"
        "• <b>Подгруппа</b> — фильтрует расписание под вашу подгруппу (1-я или 2-я), скрывая лишние лабораторные/практики.\n"
        "• <b>Утренний дайджест (07:30)</b> — бот автоматически присылает расписание на сегодня утром.\n"
        "• <b>Вечерний дайджест (20:00)</b> — бот присылает расписание на завтра вечером.\n"
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
    if not query or not query.data or not update.effective_user:
        return

    user_id = update.effective_user.id
    data = query.data

    # Переключение утреннего дайджеста
    if data == "toggle_notif_morning":
        new_state = await db.toggle_notification(user_id, "morning")
        status_str = "включен (07:30)" if new_state else "выключен"
        await query.answer(f"Утренний дайджест {status_str}!")
        user = await db.get_user(user_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_settings_inline_keyboard(user)
            )
        except BadRequest:
            pass

    # Переключение вечернего дайджеста
    elif data == "toggle_notif_evening":
        new_state = await db.toggle_notification(user_id, "evening")
        status_str = "включен (20:00)" if new_state else "выключен"
        await query.answer(f"Вечерний дайджест {status_str}!")
        user = await db.get_user(user_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_settings_inline_keyboard(user)
            )
        except BadRequest:
            pass

    # Переключение опции «Без пар не будить»
    elif data == "toggle_notif_only_lessons":
        new_state = await db.toggle_notification(user_id, "only_lessons")
        status_str = "включен (тишина)" if new_state else "выключен"
        await query.answer(f"Режим без пар: {status_str}!")
        user = await db.get_user(user_id)
        try:
            await query.edit_message_reply_markup(
                reply_markup=get_settings_inline_keyboard(user)
            )
        except BadRequest:
            pass

    # Открытие меню выбора подгруппы
    elif data == "settings_subgroup":
        await query.answer()
        text = (
            "👥 <b>Выберите вашу подгруппу:</b>\n\n"
            "• <i>Вся группа</i> — отображаются все пары без фильтрации.\n"
            "• <i>1-я / 2-я подгруппа</i> — отображаются только общие пары и пары вашей подгруппы."
        )
        try:
            await query.edit_message_text(
                text=text,
                reply_markup=get_subgroup_select_keyboard(),
                parse_mode=ParseMode.HTML,
            )
        except BadRequest:
            pass

    # Установка выбранной подгруппы (0, 1 или 2)
    elif data.startswith("set_subgroup_"):
        sub_num = int(data.split("_")[-1])
        await db.update_user_subgroup(user_id, sub_num)
        sub_label = "Вся группа" if sub_num == 0 else f"{sub_num}-я подгруппа"
        await query.answer(f"Выбрана: {sub_label}")
        # Возврат в главное меню настроек
        user = await db.get_user(user_id)
        await cmd_settings(update, context)

    # Кнопка «Назад» в настройки
    elif data == "settings_back":
        await query.answer()
        user = await db.get_user(user_id)
        await cmd_settings(update, context)
