import json
import logging
import asyncio
from datetime import datetime
import aiosqlite
from src.config import DB_PATH, TIMEZONE

logger = logging.getLogger(__name__)


class Database:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self._conn: aiosqlite.Connection | None = None
        self._lock: asyncio.Lock | None = None
        self._lock_loop = None

    @property
    def lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        if self._lock is None or self._lock_loop != loop:
            self._lock = asyncio.Lock()
            self._lock_loop = loop
        return self._lock

    async def _get_conn(self) -> aiosqlite.Connection:
        """Возвращает или создает долгоживущее соединение с SQLite для текущего event loop."""
        current_loop = asyncio.get_running_loop()
        if self._conn is not None:
            conn_loop = getattr(self._conn, "_loop", None)
            if conn_loop != current_loop:
                self._conn = None

        if self._conn is None:
            self._conn = await aiosqlite.connect(self.db_path)
            self._conn.row_factory = aiosqlite.Row
            await self._conn.execute("PRAGMA journal_mode = WAL;")
            await self._conn.execute("PRAGMA synchronous = NORMAL;")
        return self._conn

    async def close(self) -> None:
        """Закрывает соединение с БД."""
        async with self.lock:
            if self._conn is not None:
                try:
                    await self._conn.close()
                except Exception:
                    pass
                self._conn = None

    async def init(self) -> None:
        """Инициализация таблиц базы данных, миграции и создание индексов."""
        async with self.lock:
            conn = await self._get_conn()

            # Миграция schedule_cache (если был id вместо group_id)
            async with conn.execute("PRAGMA table_info(schedule_cache)") as cursor:
                columns = [row[1] for row in await cursor.fetchall()]
                if columns and "group_id" not in columns:
                    logger.info("Миграция таблицы schedule_cache: переименование колонки id в group_id...")
                    try:
                        await conn.execute("ALTER TABLE schedule_cache RENAME COLUMN id TO group_id;")
                        await conn.execute("UPDATE schedule_cache SET group_id = 1671 WHERE group_id = 1;")
                    except Exception as e:
                        logger.warning(f"Ошибка при ALTER TABLE: {e}, пересоздаем таблицу кэша...")
                        await conn.execute("DROP TABLE IF EXISTS schedule_cache;")

            # 1. Таблица кэша расписаний
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_cache (
                    group_id INTEGER PRIMARY KEY,
                    json_data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # 2. Таблица пользователей и настроек
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    username TEXT,
                    first_name TEXT,
                    group_id INTEGER DEFAULT 1671,
                    subgroup INTEGER DEFAULT 0,
                    notify_morning INTEGER DEFAULT 0,
                    notify_morning_time TEXT DEFAULT '07:30',
                    notify_evening INTEGER DEFAULT 0,
                    notify_evening_time TEXT DEFAULT '20:00',
                    notify_only_with_lessons INTEGER DEFAULT 1,
                    is_blocked INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    last_active TEXT NOT NULL
                );
                """
            )

            # Проверка наличия новых колонок в users
            async with conn.execute("PRAGMA table_info(users)") as cursor:
                user_cols = [row[1] for row in await cursor.fetchall()]
                if "notify_only_with_lessons" not in user_cols:
                    await conn.execute(
                        "ALTER TABLE users ADD COLUMN notify_only_with_lessons INTEGER DEFAULT 1;"
                    )
                if "is_blocked" not in user_cols:
                    await conn.execute(
                        "ALTER TABLE users ADD COLUMN is_blocked INTEGER DEFAULT 0;"
                    )

            # 3. Индексы для оптимизации поиска и рассылок
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_morning ON users(notify_morning);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_evening ON users(notify_evening);"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_group ON users(group_id);"
            )

            # 4. Таблица слепков расписания для обнаружения изменений (diff)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schedule_snapshots (
                    group_id INTEGER PRIMARY KEY,
                    snapshot_hash TEXT NOT NULL,
                    json_data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # Удаляем таблицу homework, если она существовала
            await conn.execute("DROP TABLE IF EXISTS homework;")

            await conn.commit()
            logger.info("База данных SQLite успешно инициализирована.")

    # --- Работа с кэшем расписания ---

    async def save_schedule(self, group_id: int, data: dict) -> None:
        """Сохраняет JSON расписания группы в SQLite."""
        async with self.lock:
            try:
                conn = await self._get_conn()
                now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
                json_str = json.dumps(data, ensure_ascii=False)
                await conn.execute(
                    """
                    INSERT INTO schedule_cache (group_id, json_data, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(group_id) DO UPDATE SET
                        json_data = excluded.json_data,
                        updated_at = excluded.updated_at;
                    """,
                    (group_id, json_str, now_str),
                )
                await conn.commit()
            except Exception as e:
                logger.error(f"Ошибка сохранения кэша в SQLite (group_id={group_id}): {e}")

    async def load_schedule(self, group_id: int) -> dict | None:
        """Загружает JSON расписания группы из SQLite."""
        data, _ = await self.load_schedule_with_meta(group_id)
        return data

    async def load_schedule_with_meta(self, group_id: int) -> tuple[dict | None, str | None]:
        """Загружает JSON расписания и дату сохранения updated_at."""
        async with self.lock:
            try:
                conn = await self._get_conn()
                async with conn.execute(
                    "SELECT json_data, updated_at FROM schedule_cache WHERE group_id = ?",
                    (group_id,),
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        return json.loads(row["json_data"]), row["updated_at"]

                    # Для обратной совместимости
                    if group_id == 1671:
                        async with conn.execute(
                            "SELECT json_data, updated_at FROM schedule_cache WHERE group_id = 1"
                        ) as legacy_cursor:
                            legacy_row = await legacy_cursor.fetchone()
                            if legacy_row:
                                return json.loads(legacy_row["json_data"]), legacy_row["updated_at"]
                return None, None
            except Exception as e:
                logger.error(f"Ошибка чтения кэша из SQLite (group_id={group_id}): {e}")
                return None, None

    # --- Работа с пользователями и настройками ---

    async def register_or_update_user(
        self, user_id: int, username: str | None = None, first_name: str | None = None
    ) -> dict:
        """Регистрирует нового пользователя или обновляет время последней активности."""
        async with self.lock:
            conn = await self._get_conn()
            now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")

            async with conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                user = await cursor.fetchone()

            if user is None:
                await conn.execute(
                    """
                    INSERT INTO users (
                        user_id, username, first_name, group_id, subgroup,
                        notify_morning, notify_morning_time,
                        notify_evening, notify_evening_time,
                        notify_only_with_lessons, is_blocked,
                        created_at, last_active
                    ) VALUES (?, ?, ?, 1671, 0, 0, '07:30', 0, '20:00', 1, 0, ?, ?)
                    """,
                    (user_id, username, first_name, now_str, now_str),
                )
            else:
                await conn.execute(
                    """
                    UPDATE users SET
                        username = ?,
                        first_name = ?,
                        last_active = ?,
                        is_blocked = 0
                    WHERE user_id = ?
                    """,
                    (username, first_name, now_str, user_id),
                )
            await conn.commit()

            async with conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else {}

    async def get_user(self, user_id: int) -> dict | None:
        """Возвращает данные пользователя."""
        async with self.lock:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT * FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None

    async def update_user_subgroup(self, user_id: int, subgroup: int) -> None:
        """Устанавливает выбранную подгруппу (0 - вся группа, 1 или 2)."""
        async with self.lock:
            conn = await self._get_conn()
            await conn.execute(
                "UPDATE users SET subgroup = ? WHERE user_id = ?",
                (subgroup, user_id),
            )
            await conn.commit()

    async def toggle_notification(self, user_id: int, notif_type: str) -> bool:
        """Переключает статус уведомления (morning, evening, only_lessons)."""
        col_map = {
            "morning": "notify_morning",
            "evening": "notify_evening",
            "only_lessons": "notify_only_with_lessons",
        }
        column = col_map.get(notif_type, "notify_morning")
        async with self.lock:
            conn = await self._get_conn()
            async with conn.execute(
                f"SELECT {column} FROM users WHERE user_id = ?", (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                current_state = row[column] if row else 0

            new_state = 0 if current_state else 1
            await conn.execute(
                f"UPDATE users SET {column} = ? WHERE user_id = ?",
                (new_state, user_id),
            )
            await conn.commit()
            return bool(new_state)

    async def mark_user_blocked(self, user_id: int) -> None:
        """Отмечает пользователя как заблокировавшего бота."""
        async with self.lock:
            conn = await self._get_conn()
            await conn.execute(
                """
                UPDATE users SET
                    is_blocked = 1,
                    notify_morning = 0,
                    notify_evening = 0
                WHERE user_id = ?
                """,
                (user_id,),
            )
            await conn.commit()

    async def get_users_for_morning_digest(self) -> list[dict]:
        """Возвращает пользователей с включенными утренними уведомлениями."""
        async with self.lock:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT * FROM users WHERE notify_morning = 1 AND is_blocked = 0"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_users_for_evening_digest(self) -> list[dict]:
        """Возвращает пользователей с включенными вечерними уведомлениями."""
        async with self.lock:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT * FROM users WHERE notify_evening = 1 AND is_blocked = 0"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_all_active_users(self) -> list[dict]:
        """Возвращает всех активных пользователей для оповещений об изменениях."""
        async with self.lock:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT * FROM users WHERE is_blocked = 0"
            ) as cursor:
                rows = await cursor.fetchall()
                return [dict(r) for r in rows]

    async def get_bot_stats(self) -> dict:
        """Возвращает агрегированную статистику использования бота."""
        async with self.lock:
            conn = await self._get_conn()
            today_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d")

            async with conn.execute("SELECT COUNT(*) FROM users") as cur:
                total_users = (await cur.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM users WHERE last_active LIKE ?", (f"{today_str}%",)) as cur:
                active_today = (await cur.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM users WHERE notify_morning = 1") as cur:
                morning_notif = (await cur.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM users WHERE notify_evening = 1") as cur:
                evening_notif = (await cur.fetchone())[0]
            async with conn.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1") as cur:
                blocked_users = (await cur.fetchone())[0]

            return {
                "total_users": total_users,
                "active_today": active_today,
                "morning_notif": morning_notif,
                "evening_notif": evening_notif,
                "blocked_users": blocked_users,
            }

    # --- Снапшоты расписания (Schedule Diff / Alerts) ---

    async def get_schedule_snapshot(self, group_id: int) -> tuple[str, dict] | None:
        """Возвращает хеш и сохраненный JSON слепка расписания."""
        async with self.lock:
            conn = await self._get_conn()
            async with conn.execute(
                "SELECT snapshot_hash, json_data FROM schedule_snapshots WHERE group_id = ?",
                (group_id,),
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row["snapshot_hash"], json.loads(row["json_data"])
                return None

    async def save_schedule_snapshot(self, group_id: int, snapshot_hash: str, data: dict) -> None:
        """Сохраняет актуальный слепок расписания для отслеживания изменений."""
        async with self.lock:
            conn = await self._get_conn()
            now_str = datetime.now(TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")
            json_str = json.dumps(data, ensure_ascii=False)
            await conn.execute(
                """
                INSERT INTO schedule_snapshots (group_id, snapshot_hash, json_data, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(group_id) DO UPDATE SET
                    snapshot_hash = excluded.snapshot_hash,
                    json_data = excluded.json_data,
                    updated_at = excluded.updated_at;
                """,
                (group_id, snapshot_hash, json_str, now_str),
            )
            await conn.commit()


db = Database()


