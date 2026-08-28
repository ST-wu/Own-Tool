import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator
from playwright.async_api import (
    async_playwright,
    Playwright,
    Browser,
    BrowserContext,
    Page,
    Error as PlaywrightError,
)
from config import settings
from core.logger import logger


class BrowserManager:
    """
    Playwright 瀏覽器常駐管理器
    負責生命週期管理、並發控制、沙盒 Context 隔離與崩潰自癒
    """

    def __init__(self) -> None:
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._semaphore = asyncio.Semaphore(settings.MAX_CONCURRENT_CONTEXTS)
        self._lock = asyncio.Lock()
        self._is_running = False

    @property
    def is_running(self) -> bool:
        return self._is_running and self._browser is not None and self._browser.is_connected()

    async def start(self) -> None:
        """啟動常駐 Playwright 與主瀏覽器實例"""
        async with self._lock:
            if self._is_running and self._browser and self._browser.is_connected():
                return

            logger.info(f"啟動 Playwright 常駐引擎 [Type: {settings.BROWSER_TYPE}, Headless: {settings.HEADLESS}]...")
            self._playwright = await async_playwright().start()

            browser_type = getattr(self._playwright, settings.BROWSER_TYPE)
            self._browser = await browser_type.launch(
                headless=settings.HEADLESS,
                args=["--no-sandbox", "--disable-dev-shm-usage"] if settings.BROWSER_TYPE == "chromium" else [],
            )
            self._is_running = True
            logger.info("Playwright 瀏覽器常駐引擎已成功就緒")

    async def stop(self) -> None:
        """優雅關閉瀏覽器與釋放資源"""
        async with self._lock:
            self._is_running = False
            if self._browser:
                logger.info("關閉 Playwright 瀏覽器實例...")
                try:
                    await self._browser.close()
                except Exception as e:
                    logger.warning(f"[ERROR_SUMMARY] 關閉瀏覽器時發生非致命異常: {type(e).__name__}: {e}")
                self._browser = None

            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception as e:
                    logger.warning(f"[ERROR_SUMMARY] 停止 Playwright 時發生非致命異常: {type(e).__name__}: {e}")
                self._playwright = None

            logger.info("Playwright 資源清理完成")

    async def _ensure_healthy_browser(self) -> Browser:
        """自癒保護機制：確保瀏覽器處於連線可用狀態"""
        if not self._browser or not self._browser.is_connected():
            logger.warning("[AUTO_RECOVERY] 偵測到瀏覽器實例離線，觸發自動重啟自癒程序...")
            await self.start()
        if not self._browser:
            raise RuntimeError("Browser instance could not be initialized")
        return self._browser

    @asynccontextmanager
    async def get_isolated_context(self) -> AsyncGenerator[BrowserContext, None]:
        """
        取得獨立隔離之 BrowserContext (Context Manager 模式)
        透過信號旗標控制最大並發，完成後自動釋放隔離沙盒
        """
        await self._semaphore.acquire()
        context: BrowserContext | None = None
        try:
            browser = await self._ensure_healthy_browser()
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                ignore_https_errors=False,
            )
            context.set_default_timeout(settings.CONTEXT_TIMEOUT_MS)
            yield context
        finally:
            if context:
                try:
                    if self._browser and self._browser.is_connected():
                        await context.close()
                except Exception as e:
                    logger.warning(f"[ERROR_SUMMARY] 釋放 Context 時異常: {type(e).__name__}: {e}")
            self._semaphore.release()

    async def capture_failure_artifact(self, page: Page | None, task_name: str) -> str | None:
        """當任務失敗時，自動儲存當下畫面快照以利審計排查"""
        if not page or page.is_closed():
            return None

        try:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            failure_dir = settings.ARTIFACTS_DIR / "failures"
            failure_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = failure_dir / f"fail_{task_name}_{timestamp}.png"
            await page.screenshot(path=str(screenshot_path), full_page=True)
            logger.info(f"已生成失敗畫面審計截圖: {screenshot_path}")
            return str(screenshot_path)
        except Exception as e:
            logger.warning(f"[ERROR_SUMMARY] 捕獲失敗快照時發生異常: {type(e).__name__}: {e}")
            return None

    async def check_health(self) -> dict[str, any]:
        """
        執行輕量探活檢測：開啟探針 Page 執行 JavaScript 算式並量測延遲
        """
        # Guard clause: 檢查核心常駐標記
        if not self.is_running:
            return {"status": "unhealthy", "error": "Browser is not running"}

        start_time = asyncio.get_event_loop().time()
        try:
            async with self.get_isolated_context() as context:
                page = await context.new_page()
                result = await page.evaluate("() => 1 + 1")
                latency_ms = round((asyncio.get_event_loop().time() - start_time) * 1000, 2)
                return {
                    "status": "healthy" if result == 2 else "degraded",
                    "latency_ms": latency_ms,
                    "browser_connected": self._browser.is_connected() if self._browser else False,
                    "available_permits": self._semaphore._value,
                }
        except Exception as e:
            logger.error(f"[ERROR_SUMMARY] 健康檢查探測失敗: {type(e).__name__}: {e}")
            return {
                "status": "unhealthy",
                "error": f"{type(e).__name__}: {str(e)}",
            }


# 全域單例
browser_manager = BrowserManager()
