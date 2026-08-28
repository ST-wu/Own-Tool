from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field
from playwright.async_api import BrowserContext, Page
from config import settings
from tasks.base import BaseTask, TaskMetadata
from core.logger import logger


class WebInspectorParams(BaseModel):
    """網頁巡檢輸入參數模型"""
    url: str = Field(..., description="目標網址 (需包含 http:// 或 https://)")
    wait_until: str = Field(default="domcontentloaded", description="等待頁面狀態: load / domcontentloaded / networkidle")
    extract_selector: str | None = Field(default=None, description="可選之文字擷取 CSS Selector")
    take_screenshot: bool = Field(default=False, description="是否拍攝並保存當下完整頁面快照")


class WebInspectorTask(BaseTask):
    """通用網頁巡檢與資料擷取任務插件"""

    metadata = TaskMetadata(
        name="web_inspector",
        description="導航至目標網頁，檢查回應狀態碼、標題，並支援選擇性文字擷取與截圖存檔",
        version="1.0.0",
        author="PlaywrightDaemon",
        tags=["web", "scraper", "monitoring"],
        enabled=True,
    )
    param_model = WebInspectorParams

    async def run(
        self,
        page: Page,
        context: BrowserContext,
        params: WebInspectorParams,
    ) -> dict[str, Any]:
        # Guard clause: 簡單驗證 URL 格式
        if not params.url.startswith(("http://", "https://")):
            raise ValueError(f"Invalid URL protocol for '{params.url}'. Must start with http:// or https://")

        logger.info(f"[WebInspector] 導航至: {params.url}")
        response = await page.goto(params.url, wait_until=params.wait_until)

        title = await page.title()
        status_code = response.status if response else None

        extracted_text = None
        if params.extract_selector:
            try:
                locator = page.locator(params.extract_selector).first
                if await locator.count() > 0:
                    extracted_text = await locator.inner_text()
            except Exception as e:
                logger.warning(f"[WebInspector] 擷取元素失敗: {type(e).__name__}: {e}")

        screenshot_file = None
        if params.take_screenshot:
            screenshot_dir = settings.ARTIFACTS_DIR / "screenshots"
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_file = screenshot_dir / f"inspect_{timestamp}.png"
            await page.screenshot(path=str(screenshot_file), full_page=True)
            logger.info(f"[WebInspector] 已存檔快照: {screenshot_file}")

        return {
            "url": params.url,
            "status_code": status_code,
            "title": title,
            "extracted_text": extracted_text,
            "screenshot_path": str(screenshot_file) if screenshot_file else None,
        }
