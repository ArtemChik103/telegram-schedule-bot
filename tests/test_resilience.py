import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from telegram.error import TimedOut, NetworkError, BadRequest
from telegram.request import HTTPXRequest
from src.bot import ResilientHTTPXRequest
from src.handlers.error import error_handler


@pytest.mark.asyncio
async def test_resilient_httpx_request_retries_on_timeout():
    """Проверяет, что при таймауте для исходящих запросов выполняются повторные попытки."""
    req = ResilientHTTPXRequest()
    mock_super = AsyncMock(side_effect=[TimedOut("Connection timeout"), (200, b'{"ok": true}')])

    with patch.object(HTTPXRequest, "do_request", mock_super):
        code, payload = await req.do_request(
            url="https://api.telegram.org/bot123/sendMessage",
            method="POST",
        )

    assert code == 200
    assert payload == b'{"ok": true}'
    assert mock_super.call_count == 2


@pytest.mark.asyncio
async def test_resilient_httpx_request_raises_after_max_retries():
    """Проверяет, что если сетевой сбой не уходит, исключение поднимается после исчерпания попыток."""
    req = ResilientHTTPXRequest()
    mock_super = AsyncMock(side_effect=TimedOut("Persistent timeout"))

    with patch.object(HTTPXRequest, "do_request", mock_super):
        with pytest.raises(TimedOut):
            await req.do_request(
                url="https://api.telegram.org/bot123/sendMessage",
                method="POST",
            )

    assert mock_super.call_count == 3


@pytest.mark.asyncio
async def test_resilient_httpx_request_does_not_retry_get_updates():
    """Проверяет, что getUpdates не ретраится внутри do_request (PTB сам рулит поллингом)."""
    req = ResilientHTTPXRequest()
    mock_super = AsyncMock(side_effect=TimedOut("Long polling timeout"))

    with patch.object(HTTPXRequest, "do_request", mock_super):
        with pytest.raises(TimedOut):
            await req.do_request(
                url="https://api.telegram.org/bot123/getUpdates",
                method="POST",
            )

    assert mock_super.call_count == 1


@pytest.mark.asyncio
async def test_error_handler_suppresses_timed_out_with_update():
    """Проверяет, что TimedOut при наличии update НЕ отправляет алерт админу."""
    context = MagicMock()
    context.error = TimedOut("Timed out")
    context.bot.send_message = AsyncMock()

    dummy_update = MagicMock()
    dummy_update.__str__.return_value = "Update(message=Message(...))"

    with patch("src.handlers.error.ADMIN_ID", 123456789):
        await error_handler(dummy_update, context)

    context.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_error_handler_suppresses_network_error():
    """Проверяет, что NetworkError НЕ отправляет алерт админу."""
    context = MagicMock()
    context.error = NetworkError("httpx.ConnectError: Connection refused")
    context.bot.send_message = AsyncMock()

    dummy_update = MagicMock()

    with patch("src.handlers.error.ADMIN_ID", 123456789):
        await error_handler(dummy_update, context)

    context.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_error_handler_suppresses_benign_telegram_errors():
    """Проверяет, что устаревшие callback queries или блокировки бота админу не отправляются."""
    benign_errors = [
        BadRequest("Query is too old and response timeout expired or query id is invalid"),
        BadRequest("Message is not modified: specified new message content and reply markup are exactly the same"),
        BadRequest("Forbidden: bot was blocked by the user"),
    ]

    for err in benign_errors:
        context = MagicMock()
        context.error = err
        context.bot.send_message = AsyncMock()

        dummy_update = MagicMock()

        with patch("src.handlers.error.ADMIN_ID", 123456789):
            await error_handler(dummy_update, context)

        context.bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_error_handler_alerts_on_real_exceptions():
    """Проверяет, что настоящие необработанные ошибки приложения отправляются админу."""
    context = MagicMock()
    context.error = ValueError("Unexpected parsing failure")
    context.bot.send_message = AsyncMock()

    dummy_update = MagicMock()
    dummy_update.__str__.return_value = "Update(message=Message(...))"

    with patch("src.handlers.error.ADMIN_ID", 123456789):
        await error_handler(dummy_update, context)

    context.bot.send_message.assert_called_once()
    call_args = context.bot.send_message.call_args
    assert call_args.kwargs["chat_id"] == 123456789
    assert "Unexpected parsing failure" in call_args.kwargs["text"]
    assert "Ошибка в работе бота!" in call_args.kwargs["text"]
