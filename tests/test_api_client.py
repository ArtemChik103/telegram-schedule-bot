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
