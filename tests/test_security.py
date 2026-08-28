import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from config import settings


@pytest.mark.asyncio
async def test_security_missing_api_key():
    """驗證缺少 X-API-Key 標頭時應被 401 攔截"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/tasks")
        assert response.status_code == 401
        assert "Missing authentication key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_security_invalid_api_key():
    """驗證提供錯誤 API Key 時應被 401 攔截"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/tasks",
            headers={"X-API-Key": "wrong-secret-key"},
        )
        assert response.status_code == 401
        assert "Invalid authentication key" in response.json()["detail"]


@pytest.mark.asyncio
async def test_security_valid_api_key():
    """驗證合法 API Key 可通過鑑權"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/tasks",
            headers={"X-API-Key": settings.API_SECRET_KEY},
        )
        assert response.status_code == 200
        assert isinstance(response.json(), list)
