import pytest
from unittest.mock import AsyncMock
from src.services.notification_service import send_safe_message


@pytest.mark.asyncio
async def test_send_safe_message_success():
    bot_mock = AsyncMock()
    bot_mock.send_message = AsyncMock(return_value=True)

    result = await send_safe_message(bot_mock, 123456, "Тестовое сообщение")
    assert result is True
    bot_mock.send_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_safe_message_group_chat():
    bot_mock = AsyncMock()
    bot_mock.send_message = AsyncMock(return_value=True)

    result = await send_safe_message(bot_mock, -1001234567890, "Тестовое в группу")
    assert result is True
    bot_mock.send_message.assert_awaited_once()
    assert bot_mock.send_message.call_args.kwargs["chat_id"] == -1001234567890

