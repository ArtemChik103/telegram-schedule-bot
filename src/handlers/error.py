import html
import logging
import traceback
from telegram.constants import ParseMode
from telegram.ext import CallbackContext
from telegram.error import NetworkError, TimedOut, RetryAfter
from src.config import ADMIN_ID

logger = logging.getLogger(__name__)

# Временные сетевые сбои поллинга (обрыв TCP, SSL-рассинхрон, таймауты get_updates)
# python-telegram-bot автоматически восстанавливает соединение после них.
TRANSIENT_POLLING_ERRORS = (NetworkError, TimedOut, RetryAfter)


async def error_handler(update: object, context: CallbackContext) -> None:
    """Глобальный обработчик ошибок бота с безопасной отправкой отчета админу."""
    err = context.error

    # Если ошибка произошла во время фонового опроса Telegram (update is None)
    # и вызвана временными сетевыми сбоями/SSL-хэндшейком — логируем и не спамим админу
    if update is None and isinstance(err, TRANSIENT_POLLING_ERRORS):
        logger.warning(
            f"Временный сбой сети при опросе Telegram (авто-восстановление): {err}"
        )
        return

    logger.error("Исключение при обработке update:", exc_info=err)

    if not ADMIN_ID:
        return

    try:
        tb_list = traceback.format_exception(
            None, err, err.__traceback__ if err else None
        )
        tb_string = "".join(tb_list)

        escaped_update = html.escape(str(update)) if update else "None"
        escaped_error = html.escape(str(context.error))
        escaped_tb = html.escape(tb_string[-2000:])  # последние 2000 символов

        message = (
            "🚨 <b>Ошибка в работе бота!</b>\n\n"
            f"<b>Update:</b>\n<code>{escaped_update[:500]}</code>\n\n"
            f"<b>Error:</b>\n<code>{escaped_error}</code>\n\n"
            f"<b>Traceback:</b>\n<pre>{escaped_tb}</pre>"
        )

        await context.bot.send_message(
            chat_id=ADMIN_ID,
            text=message,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.error(f"Не удалось отправить отчет об ошибке администратору: {e}")
