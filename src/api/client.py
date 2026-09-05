import time
import logging
import asyncio
import httpx
from src.config import API_BASE_URL, CACHE_TTL_SECONDS, GROUP_ID
from src.database.db import db

logger = logging.getLogger(__name__)


class AmSUApiClient:
    def __init__(self, base_url: str = API_BASE_URL, ttl: int = CACHE_TTL_SECONDS):
        self.base_url = base_url
        self.ttl = ttl
        # In-memory кэш: {group_id: (data, timestamp)}
        self._memory_cache: dict[int | str, tuple[dict | list, float]] = {}
        self._client: httpx.AsyncClient | None = None
        self._group_lock: asyncio.Lock | None = None
        self._teachers_list_lock: asyncio.Lock | None = None
        self._teacher_locks: dict[int, asyncio.Lock] = {}

    @property
    def group_lock(self) -> asyncio.Lock:
        if self._group_lock is None:
            self._group_lock = asyncio.Lock()
        return self._group_lock

    @property
    def teachers_list_lock(self) -> asyncio.Lock:
        if self._teachers_list_lock is None:
            self._teachers_list_lock = asyncio.Lock()
        return self._teachers_list_lock

    def get_teacher_lock(self, teacher_id: int) -> asyncio.Lock:
        if teacher_id not in self._teacher_locks:
            self._teacher_locks[teacher_id] = asyncio.Lock()
        return self._teacher_locks[teacher_id]

    def _get_client(self) -> httpx.AsyncClient:
        """Возвращает или создает долгоживущий асинхронный HTTP-клиент."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=6.0),
                headers={"User-Agent": "AmSU-Schedule-Bot/2.0"},
                limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
            )
        return self._client

    async def close(self) -> None:
        """Закрывает HTTP-клиент при остановке приложения."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def get_group_schedule(
        self, group_id: int = GROUP_ID, force_refresh: bool = False
    ) -> tuple[dict | None, bool]:
        """
        Получает расписание группы.
        Возвращает кортеж (data, is_fallback), где is_fallback=True означает,
        что данные взяты из резервной SQLite-базы из-за недоступности API.
        Защищен от Cache Stampede через asyncio.Lock.
        """
        now = time.time()

        # 1. Быстрая проверка кэша в памяти
        if not force_refresh and group_id in self._memory_cache:
            cached_data, cached_at = self._memory_cache[group_id]
            if now - cached_at < self.ttl:
                return cached_data, False

        data = None
        is_fallback = False

        # 2. Захватываем блокировку для предотвращения thundering herd
        async with self.group_lock:
            now = time.time()
            if not force_refresh and group_id in self._memory_cache:
                cached_data, cached_at = self._memory_cache[group_id]
                if now - cached_at < self.ttl:
                    return cached_data, False

            url = f"{self.base_url}/group/{group_id}"
            try:
                client = self._get_client()
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
            except Exception as e:
                logger.warning(
                    f"⚠️ API АмГУ недоступен ({url}): {e}. Загружаем из SQLite..."
                )
                db_data = await db.load_schedule(group_id)
                if db_data:
                    self._memory_cache[group_id] = (db_data, now)
                    return db_data, True
                return None, False

        # 3. Обогащаем расписание группы информацией о потоках вне блокировки
        try:
            await self.enrich_group_schedule_streams(data)
        except Exception as stream_err:
            logger.warning(f"Ошибка при определении потоков: {stream_err}")

        # Обновляем in-memory кэш и базу SQLite
        self._memory_cache[group_id] = (data, now)
        await db.save_schedule(group_id, data)
        return data, False

    async def enrich_group_schedule_streams(self, data: dict) -> dict:
        """
        Обогащает расписание группы информацией о потоковых занятиях:
        опрашивает расписания преподавателей и находит пары, где преподаватель
        ведет занятие одновременно у нашей группы и у других групп.
        """
        lines = data.get("timetable_tamplate_lines", [])
        if not lines:
            return data

        group_id = data.get("group", {}).get("id") or GROUP_ID

        # Собираем всех уникальных преподавателей группы
        person_ids = list({l.get("person_id") for l in lines if isinstance(l, dict) and l.get("person_id")})
        if not person_ids:
            return data

        # Параллельно запрашиваем расписание всех преподавателей группы
        tasks = [self.get_teacher_schedule(pid) for pid in person_ids]
        teacher_schedules = await asyncio.gather(*tasks, return_exceptions=True)

        # Карта потоков: (person_id, weekday, parity, lesson) -> set of other group names
        stream_map: dict[tuple[int, int, int, int], set[str]] = {}
        for pid, teacher_data in zip(person_ids, teacher_schedules):
            if not teacher_data or isinstance(teacher_data, Exception):
                continue
            t_lines = teacher_data.get("timetable_tamplate_lines", [])
            for tl in t_lines:
                if not isinstance(tl, dict):
                    continue
                gid = tl.get("group_id")
                gstr = tl.get("group_str")
                if not gid or not gstr or gid == group_id:
                    continue
                w = tl.get("weekday")
                p = tl.get("parity", 0)
                les = tl.get("lesson")
                if not w or not les:
                    continue
                key = (pid, w, p, les)
                if key not in stream_map:
                    stream_map[key] = set()
                stream_map[key].add(gstr)

        # Проставляем поток в строки расписания нашей группы
        for l in lines:
            if not isinstance(l, dict):
                continue
            pid = l.get("person_id")
            w = l.get("weekday")
            p = l.get("parity", 0)
            les = l.get("lesson")
            if not pid or not w or not les:
                continue

            matched_streams = set()
            for check_p in (p, 0):
                k = (pid, w, check_p, les)
                if k in stream_map:
                    matched_streams.update(stream_map[k])

            if matched_streams:
                l["stream_with"] = sorted(list(matched_streams))

        return data

    async def get_teachers_list(self, force_refresh: bool = False) -> list[dict]:
        """
        Получает список всех преподавателей вуза (id, name).
        Кэшируется в памяти на 12 часов.
        """
        now = time.time()
        cache_key = "teachers_list"
        if not force_refresh and cache_key in self._memory_cache:
            data, cached_at = self._memory_cache[cache_key]
            if now - cached_at < 3600 * 12:
                return data

        async with self.teachers_list_lock:
            if not force_refresh and cache_key in self._memory_cache:
                data, cached_at = self._memory_cache[cache_key]
                if now - cached_at < 3600 * 12:
                    return data

            url = f"{self.base_url}/teachers"
            try:
                client = self._get_client()
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
                teachers = payload.get("teachers", []) if isinstance(payload, dict) else payload
                self._memory_cache[cache_key] = (teachers, now)
                return teachers
            except Exception as e:
                logger.warning(f"Не удалось получить список преподавателей ({url}): {e}")
                if cache_key in self._memory_cache:
                    return self._memory_cache[cache_key][0]
                return []

    async def get_teacher_schedule(
        self, teacher_id: int, force_refresh: bool = False
    ) -> dict | None:
        """
        Получает расписание занятий конкретного преподавателя по его ID.
        Кэшируется в памяти на TTL секунд.
        """
        now = time.time()
        cache_key = f"teacher_{teacher_id}"
        if not force_refresh and cache_key in self._memory_cache:
            data, cached_at = self._memory_cache[cache_key]
            if now - cached_at < self.ttl:
                return data

        t_lock = self.get_teacher_lock(teacher_id)
        async with t_lock:
            if not force_refresh and cache_key in self._memory_cache:
                data, cached_at = self._memory_cache[cache_key]
                if now - cached_at < self.ttl:
                    return data

            url = f"{self.base_url}/teacher/{teacher_id}"
            try:
                client = self._get_client()
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                self._memory_cache[cache_key] = (data, now)
                return data
            except Exception as e:
                logger.warning(
                    f"Не удалось получить расписание преподавателя {teacher_id} ({url}): {e}"
                )
                if cache_key in self._memory_cache:
                    return self._memory_cache[cache_key][0]
                return None

    def clear_memory_cache(self, key: int | str | None = None) -> None:
        """Очистка кэша в памяти."""
        if key:
            self._memory_cache.pop(key, None)
        else:
            self._memory_cache.clear()


api_client = AmSUApiClient()
