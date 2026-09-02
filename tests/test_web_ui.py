import pytest
from httpx import AsyncClient, ASGITransport
from starlette.testclient import TestClient
from main import app


@pytest.mark.asyncio
async def test_dashboard_route_serves_html():
    """驗證 GET / 首頁能成功渲染控制台 HTML"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/")
        assert response.status_code == 200
        assert "Playwright" in response.text
        assert "task-modal" in response.text


@pytest.mark.asyncio
async def test_get_log_config_endpoint():
    """驗證獲取 all_log_config.js 設定資訊端點"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/config/logs")
        assert response.status_code == 200
        data = response.json()
        assert "parsed_settings" in data
        assert "retention_days" in data["parsed_settings"]


def test_websocket_logs_connection():
    """驗證 /ws/logs 即時日誌推播 WebSocket 通道能正常連線"""
    client = TestClient(app)
    with client.websocket_connect("/ws/logs") as websocket:
        # 連線後應能接收至少一條訊息或正常關閉
        assert websocket is not None
