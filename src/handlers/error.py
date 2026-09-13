import html
import logging
import traceback
from telegram.constants import ParseMode
from telegram.ext import CallbackContext
from telegram.error import NetworkError, TimedOut, RetryAfter
from src.config import ADMIN_ID

logger = logging.getLogger(__name__)

# Сетевые и временные сбои Telegram API (таймауты, разрывы сокетов, рейтлимиты).
# Они являются внешними переходными процессами сети/хостинга и не требуют алертов в ЛС.
TRANSIENT_NETWORK_ERRORS = (NetworkError, TimedOut, RetryAfter)

# Ожидаемые некритичные описания ошибок Telegram API
BENIGN_ERROR_PATTERNS = (
    "Query is too old",
    "Message is not modified",
    "chat not found",
    "bot was blocked by the user",
    "user is deactivated",
    "have no rights to send a message",
    "bot was kicked from the supergroup",
    "bot is not a member of the supergroup",
)


async def error_handler(update: object, context: CallbackContext) -> None:
    """Глобальный обработчик ошибок бота с безопасной фильтрацией и отправкой отчета админу."""
    err = context.error
    if not err:
        return

    # 1. Сетевые таймауты и сбои транспорта Telegram API (при поллинге или отправке)
    if isinstance(err, TRANSIENT_NETWORK_ERRORS):
        logger.warning(
            f"Временный сетевой сбой Telegram API ({type(err).__name__}): {err}"
        )
        return

    # 2. Ожидаемые пользовательские/клиентские ошибки Telegram API
    err_str = str(err)
    if any(pattern in err_str for pattern in BENIGN_ERROR_PATTERNS):
        logger.info(f"Ожидаемое исключение Telegram API (игнорируется): {err}")
        return

    # 3. Реальные неожиданные ошибки приложения — пишем в лог с полным трейсбеком
    logger.error("Критическое исключение при обработке update:", exc_info=err)

    if not ADMIN_ID:
        return

    try:
        tb_list = traceback.format_exception(
            None, err, err.__traceback__ if err else None
        )
        tb_string = "".join(tb_list)

        escaped_update = html.escape(str(update)) if update else "None"
        escaped_error = html.escape(str(err))
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
            read_timeout=15.0,
            write_timeout=15.0,
            connect_timeout=10.0,
        )
    except Exception as e:
        logger.error(f"Не удалось отправить отчет об ошибке администратору: {e}")
