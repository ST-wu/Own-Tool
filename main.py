import asyncio
import json
import sys
from contextlib import asynccontextmanager
from fastapi import FastAPI
import uvicorn
from config import settings
from core.logger import logger
from core.op_logger import op_logger
from core.browser import browser_manager
from core.scheduler import scheduler
from tasks.registry import task_registry
from api.routes import router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式常駐生命週期管理 (Lifespan Context Manager)"""
    logger.info("=== 正在啟動 Playwright 常駐服務 ===")

    # 1. 執行歷史過期日誌安全清理
    op_logger.clean_expired_logs()

    # 2. 自動掃描與掛載所有內建及自訂任務插件
    task_registry.auto_discover("tasks.builtin")

    # 3. 啟動常駐 Playwright 瀏覽器引擎與連線池
    await browser_manager.start()

    # 4. 註冊定時排程 (每日執行一次日誌過期清理)
    scheduler.start()
    async def _daily_log_cleanup():
        op_logger.clean_expired_logs()

    scheduler.add_recurring_job(
        name="daily_log_retention_cleanup",
        interval_seconds=86400,
        job_func=_daily_log_cleanup,
    )

    op_logger.log(
        action="SYSTEM:STARTUP",
        status="SUCCESS",
        details={"host": settings.HOST, "port": settings.PORT, "headless": settings.HEADLESS},
    )
    logger.info(f"Playwright 常駐服務已就緒，API 監聽於 http://{settings.HOST}:{settings.PORT}")
    yield

    # 優雅停機流程 (Graceful Shutdown)
    logger.info("=== 正在停止 Playwright 常駐服務 ===")
    op_logger.log(action="SYSTEM:SHUTDOWN", status="INFO", details={"event": "graceful_shutdown"})
    await scheduler.stop()
    await browser_manager.stop()
    logger.info("Playwright 常駐服務已安全關閉")


app = FastAPI(
    title="Playwright Automation Service",
    description="高可擴充、安全、具備自我檢測能力之 Playwright 常駐應用服務",
    version="1.0.0",
    lifespan=lifespan,
)

# 掛載 API 路由
app.include_router(router)


async def run_cli_task(task_name: str, raw_params_json: str | None = None) -> None:
    """CLI 模式：單次執行指定任務插件並輸出結果"""
    # 註冊任務
    task_registry.auto_discover("tasks.builtin")
    task = task_registry.get(task_name)
    if not task:
        logger.error(f"找不到指定任務: {task_name}")
        sys.exit(1)

    params = {}
    if raw_params_json:
        try:
            params = json.loads(raw_params_json)
        except Exception as e:
            logger.error(f"[ERROR_SUMMARY] JSON 解析失敗: {type(e).__name__}: {e}")
            sys.exit(1)

    await browser_manager.start()
    try:
        result = await task.execute(params)
        status_str = "SUCCESS" if result.success else "ERROR"
        op_logger.log(
            action="CLI:RUN_TASK",
            status=status_str,
            details={"task": task_name, "success": result.success, "error": result.error},
            duration_ms=result.execution_time_ms,
        )
        print(result.model_dump_json(indent=2))
    finally:
        await browser_manager.stop()


def main():
    """主命令入口：支援 CLI 模式與 Uvicorn 服務常駐模式"""
    if len(sys.argv) > 2 and sys.argv[1] == "run-task":
        task_name = sys.argv[2]
        params_json = sys.argv[3] if len(sys.argv) > 3 else None
        asyncio.run(run_cli_task(task_name, params_json))
        return

    # 預設啟動常駐 HTTP API 服務
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
