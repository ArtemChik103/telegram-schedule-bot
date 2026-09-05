import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext
from src.config import GROUP_NAME, GROUP_ID, ADMIN_ID
from src.database.db import db
from src.api.client import api_client
from src.services.schedule_service import (
    format_bell_schedule,
    calculate_schedule_hash,
)
from src.services.notification_service import send_safe_message
from src.keyboards.markups import get_main_reply_keyboard

logger = logging.getLogger(__name__)


async def cmd_start(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /start."""
    if not update.effective_user or not update.message:
        return

    user = update.effective_user
    await db.register_or_update_user(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
    )

    welcome_text = (
        f"👋 <b>Привет, {user.first_name}!</b>\n\n"
        f"Я бот расписания группы <b>{GROUP_NAME}</b> (АмГУ).\n\n"
        f"📌 <b>Основные возможности:</b>\n"
        f"• <b>🔴 Сейчас</b> — статус текущей пары, прогресс-бар, таймер до перемены и анонс следующей пары\n"
        f"• <b>📅 На сегодня / ➡️ На завтра</b> — расписание с учетом четности\n"
        f"• <b>🗓 Интерактивная неделя</b> — удобное переключение по дням недели\n"
        f"• <b>🔔 Звонки (/bells)</b> — звонки, длительность пар и перемен\n"
        f"• <b>👨‍🏫 Преподаватель (/teacher)</b> — поиск преподавателя, его расписание и текущая аудитория\n"
        f"• <b>⚡ Авто-оповещения</b> — бот уведомит группу при изменениях в расписании!\n"
        f"• <b>⚙️ Настройки</b> — подгруппа, утренний/вечерний дайджест, тихий режим\n"
        f"• <b>📅 Экспорт в календарь</b> — импорт в Google/Apple Calendar (.ics)\n\n"
        f"<i>Выберите нужный раздел в меню ниже 👇</i>"
    )

    # В группах не спамим ReplyKeyboardMarkup
    is_group = update.effective_chat and update.effective_chat.type in ("group", "supergroup")
    markup = None if is_group else get_main_reply_keyboard()

    await update.message.reply_text(
        welcome_text,
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
    )


async def cmd_help(update: Update, context: CallbackContext) -> None:
    """Обработчик команды /help."""
    if not update.message:
        return

    help_text = (
        "📖 <b>Справка по боту расписания:</b>\n\n"
        "• <b>🔴 Сейчас (/now)</b> — статус текущей пары, прогресс-бар, таймер перемены и следующая пара.\n"
        "• <b>📅 На сегодня (/today)</b> — пары на сегодня с аудиториями и преподавателями.\n"
        "• <b>➡️ На завтра (/tomorrow)</b> — расписание на следующий учебный день.\n"
        "• <b>🗓 Эта / След. неделя (/week)</b> — интерактивный календарь (ПН-СБ).\n"
        "• <b>🔔 Звонки (/bells)</b> — расписание пар, звонков и перемен.\n"
        "• <b>👨‍🏫 Преподаватель (/teacher Фамилия)</b> — расписание преподавателя и где он находится прямо сейчас.\n"
        "• <b>⚙️ Настройки (/settings)</b> — фильтрация подгруппы (1/2), утренний (07:30) и вечерний (20:00) дайджест, режим тишины.\n"
        "• <b>/calendar</b> — скачать файл <code>.ics</code> для Google/Apple Calendar.\n"
        "• <b>/sync</b> — принудительно обновить расписание с сайта АмГУ."
    )

    is_group = update.effective_chat and update.effective_chat.type in ("group", "supergroup")
    markup = None if is_group else get_main_reply_keyboard()

    await update.message.reply_text(
        help_text,
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
    )


async def cmd_bells(update: Update, context: CallbackContext) -> None:
    """Отображает расписание звонков и перемен."""
    if not update.message:
        return

    schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
    msg = format_bell_schedule(schedule_data)
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)


async def cmd_sync(update: Update, context: CallbackContext) -> None:
    """Принудительное обновление кэша расписания из API АмГУ."""
    if not update.message:
        return

    msg = await update.message.reply_text(
        "🔄 <i>Обновляю расписание с сервера АмГУ...</i>", parse_mode=ParseMode.HTML
    )
    api_client.clear_memory_cache()
    data, is_fallback = await api_client.get_group_schedule(GROUP_ID, force_refresh=True)

    if data and not is_fallback:
        # Обновляем слепок для детектора diff
        s_hash = calculate_schedule_hash(data)
        await db.save_schedule_snapshot(GROUP_ID, s_hash, data)
        await msg.edit_text("✅ <b>Расписание успешно обновлено из API АмГУ!</b>", parse_mode=ParseMode.HTML)
    elif data and is_fallback:
        await msg.edit_text("⚠️ <b>Сервер АмГУ не ответил. Использована сохраненная копия из базы.</b>", parse_mode=ParseMode.HTML)
    else:
        await msg.edit_text("❌ <b>Не удалось связаться с сервером АмГУ.</b>", parse_mode=ParseMode.HTML)


async def cmd_stats(update: Update, context: CallbackContext) -> None:
    """Команда администратора: статистика использования бота."""
    user = update.effective_user
    if not user or user.id != ADMIN_ID:
        return

    stats = await db.get_bot_stats()
    api_data, is_fallback = await api_client.get_group_schedule(GROUP_ID)
    api_status = "⚠️ SQLite (кэш)" if is_fallback else ("✅ API АмГУ в сети" if api_data else "❌ Недоступен")

    text = (
        f"📊 <b>Статистика бота {GROUP_NAME}:</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"⚡ Активных сегодня: <b>{stats['active_today']}</b>\n"
        f"🌅 Утренние уведомления: <b>{stats['morning_notif']}</b>\n"
        f"🌙 Вечерние уведомления: <b>{stats['evening_notif']}</b>\n"
        f"🚫 Заблокировали бота: <b>{stats['blocked_users']}</b>\n"
        f"🌐 Состояние API: <b>{api_status}</b>"
    )

    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def cmd_broadcast(update: Update, context: CallbackContext) -> None:
    """Команда администратора: рассылка сообщения всем студентам группы."""
    user = update.effective_user
    if not user or user.id != ADMIN_ID or not update.message:
        return

    text_to_send = update.message.text.partition(" ")[2].strip()
    if not text_to_send:
        await update.message.reply_text(
            "ℹ️ <b>Формат рассылки:</b>\n<code>/broadcast Текст сообщения</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    status_msg = await update.message.reply_text("⏳ <i>Запуск рассылки...</i>", parse_mode=ParseMode.HTML)

    users = await db.get_all_active_users()
    sent_count = 0
    err_count = 0

    broadcast_header = f"📢 <b>Объявление группы {GROUP_NAME}:</b>\n\n"
    full_message = broadcast_header + text_to_send

    for u in users:
        success = await send_safe_message(context.bot, u["user_id"], full_message)
        if success:
            sent_count += 1
        else:
            err_count += 1

    await status_msg.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"• Успешно доставлено: <b>{sent_count}</b>\n"
        f"• Ошибок / заблокировано: <b>{err_count}</b>",
        parse_mode=ParseMode.HTML,
    )

