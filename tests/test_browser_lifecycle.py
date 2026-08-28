import pytest
from core.browser import browser_manager
from tasks.builtin.health_probe import HealthProbeTask
from tasks.builtin.web_inspector import WebInspectorTask


@pytest.mark.asyncio
async def test_health_probe_task_execution():
    """驗證內建健康探針任務於瀏覽器實體之執行流程"""
    await browser_manager.start()
    try:
        task = HealthProbeTask()
        result = await task.execute({"check_eval": True})
        assert result.success is True
        assert result.data.get("eval_result") is True
        assert result.execution_time_ms > 0
    finally:
        await browser_manager.stop()


@pytest.mark.asyncio
async def test_web_inspector_validation_guard():
    """驗證 URL 格式不合法時 Guard Clause 與例外捕捉"""
    await browser_manager.start()
    try:
        task = WebInspectorTask()
        # 傳入非 http(s) URL
        result = await task.execute({"url": "ftp://invalid-domain.com"})
        assert result.success is False
        assert "Invalid URL protocol" in result.error
    finally:
        await browser_manager.stop()
