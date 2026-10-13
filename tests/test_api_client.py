import pytest
from unittest.mock import patch, AsyncMock
from src.api.client import AmSUApiClient


@pytest.mark.asyncio
async def test_api_client_in_memory_cache():
    client = AmSUApiClient(ttl=60)
    fake_data = {"group_name": "ИС231", "current_week": 1}

    # Помещаем данные в кэш
    client._memory_cache[1671] = (fake_data, 10000000000.0)

    # Без force_refresh должен вернуть из памяти без запроса
    data, is_fallback = await client.get_group_schedule(1671, force_refresh=False)
    assert data == fake_data
    assert is_fallback is False


@pytest.mark.asyncio
async def test_api_client_fallback_to_db():
    client = AmSUApiClient(ttl=60)
    client.clear_memory_cache()

    # Симулируем падение сети и наличие данных в SQLite
    with patch("httpx.AsyncClient.get", side_effect=Exception("Network down")), \
         patch("src.database.db.db.load_schedule", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = {"group_name": "ИС231_offline"}

        data, is_fallback = await client.get_group_schedule(1671, force_refresh=True)
        assert data == {"group_name": "ИС231_offline"}
        assert is_fallback is True


def test_get_client_instantiation():
    """Проверяет, что _get_client корректно создает httpx.AsyncClient без NameError."""
    client = AmSUApiClient(connect_timeout=1.5, read_timeout=3.0)
    http_client = client._get_client()
    assert http_client is not None
    assert not http_client.is_closed
    assert http_client.timeout.connect == 1.5
    assert http_client.timeout.read == 3.0


@pytest.mark.asyncio
async def test_api_client_circuit_breaker():
    """Проверяет, что при сбое API срабатывает Circuit Breaker и повторные вызовы не идут в сеть."""
    client = AmSUApiClient(circuit_cooldown=60)
    client.clear_memory_cache()

    # 1. Первый сбой размыкает цепь
    with patch("httpx.AsyncClient.get", side_effect=Exception("Timeout")), \
         patch("src.database.db.db.load_schedule", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = {"group_name": "cached_offline"}
        data, is_fb = await client.get_group_schedule(1671, force_refresh=True)
        assert is_fb is True
        assert client.is_circuit_open() is True

    # 2. Второй вызов: сеть даже не дергается (быстрый возврат)
    with patch("httpx.AsyncClient.get") as mock_get, \
         patch("src.database.db.db.load_schedule", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = {"group_name": "cached_offline"}
        client.clear_memory_cache()
        data, is_fb = await client.get_group_schedule(1671, force_refresh=False)
        assert is_fb is True
        mock_get.assert_not_called()  # Сетевой запрос вообще не вызывался!


@pytest.mark.asyncio
async def test_api_client_offline_mode():
    """Проверяет, что при OFFLINE_MODE=True сеть полностью игнорируется."""
    client = AmSUApiClient(offline_mode=True)
    assert client.is_circuit_open() is True

    with patch("httpx.AsyncClient.get") as mock_get, \
         patch("src.database.db.db.load_schedule", new_callable=AsyncMock) as mock_load:
        mock_load.return_value = {"group_name": "pure_offline"}
        data, is_fb = await client.get_group_schedule(1671, force_refresh=False)
        assert data == {"group_name": "pure_offline"}
        assert is_fb is True
        mock_get.assert_not_called()


