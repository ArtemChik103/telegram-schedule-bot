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
        self._memory_cache: dict[int, tuple[dict, float]] = {}
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

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

        # 2. Захватываем блокировку для предотвращения thundering herd
        async with self._lock:
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

                # Обновляем in-memory кэш и базу SQLite
                self._memory_cache[group_id] = (data, now)
                await db.save_schedule(group_id, data)
                return data, False

            except Exception as e:
                logger.warning(
                    f"⚠️ API АмГУ недоступен ({url}): {e}. Загружаем из SQLite..."
                )

                # 3. Fallback: Загрузка из SQLite
                db_data = await db.load_schedule(group_id)
                if db_data:
                    self._memory_cache[group_id] = (db_data, now)
                    return db_data, True

                return None, False

    def clear_memory_cache(self, group_id: int | None = None) -> None:
        """Очистка кэша в памяти."""
        if group_id:
            self._memory_cache.pop(group_id, None)
        else:
            self._memory_cache.clear()


api_client = AmSUApiClient()
