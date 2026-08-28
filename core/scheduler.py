import asyncio
from typing import Callable, Coroutine, Any
from core.logger import logger


class TaskScheduler:
    """
    輕量非同步背景排程器
    負責定時巡檢、常駐心跳監控與週期性任務觸發
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task] = []
        self._is_running = False

    def add_recurring_job(
        self,
        name: str,
        interval_seconds: int,
        job_func: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """註冊週期性執行的非同步工作 (Guard Clause 驗證間隔)"""
        if interval_seconds <= 0:
            logger.info(f"排程工作 [{name}] 間隔設定 <= 0，略過排程註冊")
            return

        async def _runner() -> None:
            logger.info(f"排程工作 [{name}] 已啟動，執行週期: {interval_seconds}s")
            while self._is_running:
                try:
                    await asyncio.sleep(interval_seconds)
                    if not self._is_running:
                        break
                    await job_func()
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error(f"[ERROR_SUMMARY] 排程工作 [{name}] 執行異常: {type(e).__name__}: {e}")

        task = asyncio.create_task(_runner(), name=f"scheduler_job_{name}")
        self._tasks.append(task)

    def start(self) -> None:
        """標記排程器為運行狀態"""
        self._is_running = True
        logger.info("背景排程器已啟動")

    async def stop(self) -> None:
        """優雅停止所有運行中的背景排程"""
        self._is_running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()

        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        logger.info("背景排程器已停止")


# 全域單例
scheduler = TaskScheduler()
