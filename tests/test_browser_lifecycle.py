import pytest
from pydantic import BaseModel, Field
from playwright.async_api import BrowserContext, Page
from core.browser import browser_manager
from tasks.base import BaseTask, TaskMetadata


class StubEvalParams(BaseModel):
    check_eval: bool = True


class StubEvaluationTask(BaseTask):
    metadata = TaskMetadata(
        name="stub_eval_task",
        description="測試用獨立評估任務",
        version="1.0.0",
        enabled=True,
    )
    param_model = StubEvalParams

    async def run(self, page: Page, context: BrowserContext, params: StubEvalParams) -> dict:
        eval_res = await page.evaluate("() => ({ calc: 40 + 2, ready: true })")
        return {"eval_result": eval_res.get("calc") == 42}


class StubValidationParams(BaseModel):
    url: str = Field(..., description="驗證目標網址")


class StubValidationTask(BaseTask):
    metadata = TaskMetadata(
        name="stub_val_task",
        description="測試用參數校驗任務",
        version="1.0.0",
        enabled=True,
    )
    param_model = StubValidationParams

    async def run(self, page: Page, context: BrowserContext, params: StubValidationParams) -> dict:
        if not params.url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL protocol for '{params.url}'")
        return {"url": params.url}


@pytest.mark.asyncio
async def test_task_execution_in_isolated_context():
    """驗證任務於獨立沙盒瀏覽器實體之生命週期與執行流程"""
    await browser_manager.start()
    try:
        task = StubEvaluationTask()
        result = await task.execute({"check_eval": True})
        assert result.success is True
        assert result.data.get("eval_result") is True
        assert result.execution_time_ms > 0
    finally:
        await browser_manager.stop()


@pytest.mark.asyncio
async def test_task_validation_guard():
    """驗證參數不合法時 Guard Clause 與例外捕捉機制"""
    await browser_manager.start()
    try:
        task = StubValidationTask()
        result = await task.execute({"url": "ftp://invalid-domain.com"})
        assert result.success is False
        assert "Invalid URL protocol" in result.error
    finally:
        await browser_manager.stop()
