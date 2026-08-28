import pytest
from httpx import AsyncClient, ASGITransport
from main import app
from core.browser import browser_manager


@pytest.mark.asyncio
async def test_health_endpoint_response():
    """驗證健康檢查端點響應結構與探活狀態"""
    # 確保測試環境瀏覽器就緒
    await browser_manager.start()
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["service"] == "playwright-service"
            assert data["status"] in ("healthy", "operational")
            assert data["latency_ms"] is not None
            assert data["browser_connected"] is True
    finally:
        await browser_manager.stop()
