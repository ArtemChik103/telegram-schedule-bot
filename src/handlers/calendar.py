import io
import logging
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import CallbackContext
from src.config import GROUP_NAME, GROUP_ID
from src.database.db import db
from src.api.client import api_client
from src.services.ics_generator import generate_ics_calendar

logger = logging.getLogger(__name__)


async def export_calendar_handler(update: Update, context: CallbackContext) -> None:
    """Генерирует и отправляет файл .ics для импорта в календарь."""
    user_id = update.effective_user.id if update.effective_user else None
    if not user_id:
        return

    chat_id = update.effective_chat.id if update.effective_chat else user_id

    if update.callback_query:
        await update.callback_query.answer("Генерирую календарь...")

    user = await db.get_user(user_id)
    subgroup = user.get("subgroup", 0) if user else 0

    schedule_data, _ = await api_client.get_group_schedule(GROUP_ID)
    if not schedule_data:
        msg = "⚠️ <b>Не удалось получить данные расписания для генерации календаря.</b>"
        if update.message:
            await update.message.reply_text(msg, parse_mode=ParseMode.HTML)
        elif update.callback_query:
            await update.callback_query.message.reply_text(msg, parse_mode=ParseMode.HTML)
        return

    ics_content = generate_ics_calendar(schedule_data, subgroup=subgroup)
    file_bytes = io.BytesIO(ics_content.encode("utf-8"))
    file_bytes.name = f"{GROUP_NAME}_schedule.ics"

    caption = (
        f"📅 <b>Расписание группы {GROUP_NAME} (.ics)</b>\n\n"
        f"📥 <b>Как использовать:</b>\n"
        f"1. Нажмите на прикрепленный файл.\n"
        f"2. Откройте в приложении <b>Apple Календарь</b> (на iPhone/Mac) или импортируйте в <b>Google Календарь / Яндекс / Outlook</b>.\n"
        f"3. Все пары с аудиториями, преподавателями и напоминаниями за 15 минут добавятся в ваш личный календарь!"
    )

    await context.bot.send_document(
        chat_id=chat_id,
        document=file_bytes,
        filename=f"{GROUP_NAME}_schedule.ics",
        caption=caption,
        parse_mode=ParseMode.HTML,
    )
