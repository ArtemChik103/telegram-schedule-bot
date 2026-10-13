import os
import pytest
import tempfile
from src.database.db import Database


@pytest.mark.asyncio
async def test_database_lifecycle():
    # Создаем временный файл БД
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
        temp_db_path = tf.name

    try:
        db = Database(db_path=temp_db_path)
        await db.init()

        # 1. Тест кэша расписания
        sample_schedule = {"group_name": "ИС231", "current_week": 1}
        await db.save_schedule(1671, sample_schedule)

        loaded = await db.load_schedule(1671)
        assert loaded is not None
        assert loaded["group_name"] == "ИС231"
        assert loaded["current_week"] == 1

        # 2. Тест регистрации пользователя
        user = await db.register_or_update_user(
            user_id=12345, username="student_test", first_name="Алексей"
        )
        assert user["user_id"] == 12345
        assert user["first_name"] == "Алексей"
        assert user["subgroup"] == 0
        assert user["notify_morning"] == 0

        # 3. Тест смены подгруппы
        await db.update_user_subgroup(12345, 2)
        user_updated = await db.get_user(12345)
        assert user_updated["subgroup"] == 2

        # 4. Тест переключения уведомлений
        new_state = await db.toggle_notification(12345, "morning")
        assert new_state is True
        morning_users = await db.get_users_for_morning_digest()
        assert len(morning_users) == 1
        assert morning_users[0]["user_id"] == 12345

        # Отключаем
        off_state = await db.toggle_notification(12345, "morning")
        assert off_state is False
        morning_users_empty = await db.get_users_for_morning_digest()
        assert len(morning_users_empty) == 0

        # 5. Тест блокировки пользователя
        await db.mark_user_blocked(12345)
        user_blocked = await db.get_user(12345)
        assert user_blocked["is_blocked"] == 1
        assert user_blocked["notify_morning"] == 0

        # 6. Тест снапшотов расписания (Schedule diff)
        await db.save_schedule_snapshot(1671, "hash_123", sample_schedule)
        snapshot = await db.get_schedule_snapshot(1671)
        assert snapshot is not None
        assert snapshot[0] == "hash_123"
        assert snapshot[1]["group_name"] == "ИС231"

        # 7. Тест статистики
        stats = await db.get_bot_stats()
        assert "total_users" in stats
        assert stats["total_users"] == 1
        assert "lesson_notif" in stats
        assert "active_homework" not in stats

        # 8. Тест переключения напоминания до пары (lesson) и персонального времени дайджестов
        user2 = await db.register_or_update_user(user_id=67890, username="student2", first_name="Иван")
        assert user2["notify_lesson_reminder"] == 0

        # Включаем напоминание до пары
        lesson_on = await db.toggle_notification(67890, "lesson")
        assert lesson_on is True
        lesson_users = await db.get_users_for_lesson_reminders()
        assert len(lesson_users) == 1
        assert lesson_users[0]["user_id"] == 67890

        # Настраиваем персональное время дайджеста
        await db.update_user_digest_time(67890, "morning", "08:15")
        await db.update_user_digest_time(67890, "evening", "21:45")

        u2_data = await db.get_user(67890)
        assert u2_data["notify_morning_time"] == "08:15"
        assert u2_data["notify_morning"] == 1
        assert u2_data["notify_evening_time"] == "21:45"
        assert u2_data["notify_evening"] == 1

        # Проверка выборки по конкретному времени
        m_users_815 = await db.get_users_for_morning_digest(time_str="08:15")
        assert len(m_users_815) == 1
        assert m_users_815[0]["user_id"] == 67890

        m_users_other = await db.get_users_for_morning_digest(time_str="07:30")
        assert len(m_users_other) == 0

        e_users_2145 = await db.get_users_for_evening_digest(time_str="21:45")
        assert len(e_users_2145) == 1
        assert e_users_2145[0]["user_id"] == 67890

    finally:
        await db.close()
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass
