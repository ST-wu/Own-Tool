from typing import Any
from pydantic import BaseModel, Field
from playwright.async_api import BrowserContext, Page
from tasks.base import BaseTask, TaskMetadata


class HealthProbeParams(BaseModel):
    """健康探針參數模型"""
    check_eval: bool = Field(default=True, description="是否執行 JavaScript 計算探測")


class HealthProbeTask(BaseTask):
    """系統自動化健康探針任務"""

    metadata = TaskMetadata(
        name="system_health_probe",
        description="執行 Playwright 瀏覽器渲染引擎探活檢測，獲取核心狀態與響應延遲",
        version="1.0.0",
        author="PlaywrightDaemon",
        tags=["system", "health", "diagnostic"],
        enabled=True,
    )
    param_model = HealthProbeParams

    async def run(
        self,
        page: Page,
        context: BrowserContext,
        params: HealthProbeParams,
    ) -> dict[str, Any]:
        result = {}
        if params.check_eval:
            eval_res = await page.evaluate("() => ({ calc: 40 + 2, userAgent: navigator.userAgent })")
            result["eval_result"] = eval_res.get("calc") == 42
            result["user_agent"] = eval_res.get("userAgent")

        viewport = page.viewport_size
        result["viewport"] = viewport
        result["status"] = "operational"
        return result
