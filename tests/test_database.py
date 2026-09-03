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
        assert "active_homework" not in stats

    finally:
        await db.close()
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass
