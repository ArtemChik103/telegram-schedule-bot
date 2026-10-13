import pytest
from datetime import datetime
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
    from src.config import TIMEZONE

    context_mock = MagicMock()
    context_mock.bot = AsyncMock()
    context_mock.bot.send_message = AsyncMock(return_value=True)

    _sent_lesson_reminders.clear()

    mock_users = [{"user_id": 99999, "subgroup": 0}]
    mock_schedule = {
        "current_week": 1,
        "_cached_at_date": "2026-09-07",
        "schedule_lines": [
            {
                "lesson": 1,
                "begin_time": "2000-01-01T08:15:00.000Z",
                "end_time": "2000-01-01T09:45:00.000Z",
            },
            {
                "lesson": 2,
                "begin_time": "2000-01-01T09:55:00.000Z",
                "end_time": "2000-01-01T11:25:00.000Z",
            },
        ],
        "timetable_tamplate_lines": [
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 1,
                "discipline_str": "Архитектура ЭВМ",
                "classroom_str": "204 (ЗТ)",
                "person_str": "Петров П.П.",
            },
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 2,
                "discipline_str": "Физика",
                "classroom_str": "326 (5)",
                "person_str": "Иванов И.И.",
            },
        ],
    }

    # 1. Замораживаем время на 08:02 (за 13 минут до первой пары в 08:15)
    mock_dt_lesson1 = datetime(2026, 9, 7, 8, 2, tzinfo=TIMEZONE)

    with patch("src.database.db.db.get_users_for_lesson_reminders", new_callable=AsyncMock) as mock_get_users, \
         patch("src.api.client.api_client.get_group_schedule", new_callable=AsyncMock) as mock_get_sched, \
         patch("src.services.notification_service.datetime") as mock_datetime:

        mock_get_users.return_value = mock_users
        mock_get_sched.return_value = (mock_schedule, False)
        mock_datetime.now.return_value = mock_dt_lesson1
        mock_datetime.combine = datetime.combine

        # Вызываем джобу
        await send_lesson_reminders_job(context_mock)

        # Проверяем, что сообщение РЕАЛЬНО отправлено
        assert context_mock.bot.send_message.await_count == 1
        call_kwargs = context_mock.bot.send_message.call_args.kwargs
        assert call_kwargs["chat_id"] == 99999
        assert "Скоро начнется пара" in call_kwargs["text"]
        assert "Архитектура ЭВМ" in call_kwargs["text"]
        assert "204 (ЗТ)" in call_kwargs["text"]

        # Повторный вызов не должен дублировать отправку благодаря кэшу дедупликации
        context_mock.bot.send_message.reset_mock()
        await send_lesson_reminders_job(context_mock)
        assert context_mock.bot.send_message.await_count == 0

    # 2. Проверяем уведомление для 2-й пары со сменой корпуса: время 09:43 (за 12 мин до 09:55)
    mock_dt_lesson2 = datetime(2026, 9, 7, 9, 43, tzinfo=TIMEZONE)
    with patch("src.database.db.db.get_users_for_lesson_reminders", new_callable=AsyncMock) as mock_get_users, \
         patch("src.api.client.api_client.get_group_schedule", new_callable=AsyncMock) as mock_get_sched, \
         patch("src.services.notification_service.datetime") as mock_datetime:

        mock_get_users.return_value = mock_users
        mock_get_sched.return_value = (mock_schedule, False)
        mock_datetime.now.return_value = mock_dt_lesson2
        mock_datetime.combine = datetime.combine

        context_mock.bot.send_message.reset_mock()
        await send_lesson_reminders_job(context_mock)

        assert context_mock.bot.send_message.await_count == 1
        text_l2 = context_mock.bot.send_message.call_args.kwargs["text"]
        assert "Физика" in text_l2
        assert "326 (5)" in text_l2
        # Должно присутствовать предупреждение о смене корпуса!
        assert "смена корпуса" in text_l2.lower()
        assert "ЗТ" in text_l2
        assert "5" in text_l2


@pytest.mark.asyncio
async def test_check_and_send_scheduled_digests_job():
    from unittest.mock import patch, MagicMock
    from src.services.notification_service import (
        check_and_send_scheduled_digests_job,
        _sent_digests,
    )
    from src.config import TIMEZONE

    _sent_digests.clear()
    context_mock = MagicMock()
    context_mock.bot = AsyncMock()
    context_mock.bot.send_message = AsyncMock(return_value=True)

    mock_morning_users = [
        {"user_id": 11111, "subgroup": 1, "notify_only_with_lessons": 0}
    ]
    mock_evening_users = [
        {"user_id": 22222, "subgroup": 0, "notify_only_with_lessons": 0}
    ]

    mock_schedule = {
        "current_week": 1,
        "_cached_at_date": "2026-09-07",
        "timetable_tamplate_lines": [
            {
                "weekday": 1,
                "parity": 1,
                "lesson": 1,
                "discipline_str": "Программирование",
                "classroom_str": "204 (ЗТ)",
                "person_str": "Иванов",
                "subgroup": 1,
            },
            {
                "weekday": 2,
                "parity": 1,
                "lesson": 1,
                "discipline_str": "Математика",
                "classroom_str": "326 (5)",
                "person_str": "Петров",
                "subgroup": 0,
            },
        ],
    }

    # 1. Проверяем утро 08:30 (пользователь 11111)
    mock_dt_morning = datetime(2026, 9, 7, 8, 30, tzinfo=TIMEZONE)
    with patch("src.database.db.db.get_users_for_morning_digest", new_callable=AsyncMock) as mock_get_m, \
         patch("src.database.db.db.get_users_for_evening_digest", new_callable=AsyncMock) as mock_get_e, \
         patch("src.api.client.api_client.get_group_schedule", new_callable=AsyncMock) as mock_get_sched, \
         patch("src.services.notification_service.datetime") as mock_datetime:

        mock_get_m.return_value = mock_morning_users
        mock_get_e.return_value = []
        mock_get_sched.return_value = (mock_schedule, False)
        mock_datetime.now.return_value = mock_dt_morning
        mock_datetime.combine = datetime.combine

        await check_and_send_scheduled_digests_job(context_mock)

        assert context_mock.bot.send_message.await_count == 1
        m_call = context_mock.bot.send_message.call_args.kwargs
        assert m_call["chat_id"] == 11111
        assert "Доброе утро" in m_call["text"]
        assert "Программирование" in m_call["text"]

        # Повторный вызов в ту же минуту дедуплицируется
        context_mock.bot.send_message.reset_mock()
        await check_and_send_scheduled_digests_job(context_mock)
        assert context_mock.bot.send_message.await_count == 0

    # 2. Проверяем вечер 21:00 (пользователь 22222)
    mock_dt_evening = datetime(2026, 9, 7, 21, 0, tzinfo=TIMEZONE)
    with patch("src.database.db.db.get_users_for_morning_digest", new_callable=AsyncMock) as mock_get_m, \
         patch("src.database.db.db.get_users_for_evening_digest", new_callable=AsyncMock) as mock_get_e, \
         patch("src.api.client.api_client.get_group_schedule", new_callable=AsyncMock) as mock_get_sched, \
         patch("src.services.notification_service.datetime") as mock_datetime:

        mock_get_m.return_value = []
        mock_get_e.return_value = mock_evening_users
        mock_get_sched.return_value = (mock_schedule, False)
        mock_datetime.now.return_value = mock_dt_evening
        mock_datetime.combine = datetime.combine

        context_mock.bot.send_message.reset_mock()
        await check_and_send_scheduled_digests_job(context_mock)

        assert context_mock.bot.send_message.await_count == 1
        e_call = context_mock.bot.send_message.call_args.kwargs
        assert e_call["chat_id"] == 22222
        assert "Расписание на завтра" in e_call["text"]
        assert "Математика" in e_call["text"]




