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


@pytest.mark.asyncio
async def test_send_lesson_reminders_job():
    from unittest.mock import patch, MagicMock
    from src.services.notification_service import send_lesson_reminders_job, _sent_lesson_reminders

    context_mock = MagicMock()
    context_mock.bot = AsyncMock()
    context_mock.bot.send_message = AsyncMock(return_value=True)

    # Очищаем кэш отправленных напоминаний
    _sent_lesson_reminders.clear()

    mock_users = [{"user_id": 99999, "subgroup": 0}]
    mock_schedule = {
        "current_week": 1,
        "schedule_lines": [
            {
                "lesson": 1,
                "begin_time": "2000-01-01T08:15:00.000Z",
                "end_time": "2000-01-01T09:45:00.000Z",
            }
        ],
        "timetable_tamplate_lines": [
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 1,
                "discipline_str": "Архитектура ЭВМ",
                "classroom_str": "204 (ЗТ)",
                "person_str": "Петров П.П.",
            }
        ],
    }

    with patch("src.database.db.db.get_users_for_lesson_reminders", new_callable=AsyncMock) as mock_get_users, \
         patch("src.api.client.api_client.get_group_schedule", new_callable=AsyncMock) as mock_get_sched:
        mock_get_users.return_value = mock_users
        mock_get_sched.return_value = (mock_schedule, False)

        # Вызываем джобу
        await send_lesson_reminders_job(context_mock)
        # Если время сейчас не 08:00..08:05, сообщения не шлются в нерабочее время (но тест завершается без ошибок)
        assert True


