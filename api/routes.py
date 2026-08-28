import asyncio
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from core.browser import browser_manager
from core.security import verify_api_key
from core.logger import logger
from core.op_logger import op_logger
from tasks.registry import task_registry
from tasks.base import TaskExecutionResult
from api.schemas import (
    HealthResponse,
    RunTaskRequest,
    TaskStatusToggleRequest,
    StandardResponse,
)

router = APIRouter()
WEB_DIR = Path("web")


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def get_health_status() -> HealthResponse:
    """系統核心與 Playwright 渲染引擎狀態檢查端點"""
    health_data = await browser_manager.check_health()
    status_val = health_data.get("status", "unknown")
    latency = health_data.get("latency_ms")
    connected = health_data.get("browser_connected", False)
    permits = health_data.get("available_permits", 0)
    error_msg = health_data.get("error")

    if status_val in ("healthy", "operational"):
        op_logger.log(
            "HEALTH:CHECK",
            "INFO",
            details=f"服務運作良好 | 延遲={latency}ms | 可用連線數={permits}",
        )
    else:
        op_logger.log(
            "HEALTH:CHECK",
            "WARNING",
            details=f"服務狀態異常: {status_val} | 錯誤={error_msg}",
        )
        op_logger.log(
            "HEALTH:DIAG",
            "DEBUG",
            details="建議處置: 請檢查主機記憶體是否不足，或至終端機執行 `uv run python main.py` 重新啟動服務",
        )

    return HealthResponse(
        service="playwright-service",
        status=status_val,
        latency_ms=latency,
        browser_connected=connected,
        available_permits=permits,
        error=error_msg,
    )


@router.get(
    "/api/v1/tasks",
    dependencies=[Depends(verify_api_key)],
    tags=["Tasks"],
)
async def list_available_tasks() -> list[dict]:
    """獲取目前所有已掛載任務插件之元資料與參數規格 (JSON Schema)"""
    tasks = task_registry.list_tasks()
    op_logger.log("API:LIST_TASKS", "DEBUG", {"task_count": len(tasks)})
    return tasks


@router.post(
    "/api/v1/tasks/{task_name}/run",
    response_model=TaskExecutionResult,
    dependencies=[Depends(verify_api_key)],
    tags=["Tasks"],
)
async def run_task_by_name(
    task_name: str,
    payload: RunTaskRequest,
) -> TaskExecutionResult:
    """
    動態調度並執行指定的任務插件
    具備參數校驗、Context 沙盒隔離與錯誤畫面自存機制
    """
    task = task_registry.get(task_name)
    # Guard clause: 任務不存在
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_name}' not found in registry",
        )

    # Guard clause: 任務已停用
    if not task.metadata.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Task '{task_name}' is disabled",
        )

    logger.info(f"觸發執行任務插件: [{task_name}]")
    result = await task.execute(payload.params)
    op_logger.log(
        action=f"API:RUN_TASK:{task_name}",
        status="SUCCESS" if result.success else "ERROR",
        details={"success": result.success, "error": result.error},
        duration_ms=result.execution_time_ms,
    )
    return result


@router.post(
    "/api/v1/tasks/{task_name}/status",
    response_model=StandardResponse,
    dependencies=[Depends(verify_api_key)],
    tags=["Tasks"],
)
async def toggle_task_status(
    task_name: str,
    payload: TaskStatusToggleRequest,
) -> StandardResponse:
    """動態啟用或停用指定之任務插件"""
    success = task_registry.set_enabled(task_name, payload.enabled)
    # Guard clause: 任務不存在
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task '{task_name}' not found in registry",
        )

    op_logger.log("API:TOGGLE_STATUS", "INFO", {"task": task_name, "enabled": payload.enabled})
    return StandardResponse(
        success=True,
        message=f"Task '{task_name}' status set to enabled={payload.enabled}",
    )


@router.get("/", include_in_schema=False)
async def serve_dashboard():
    """提供 Web 控制台儀表板首頁 (Guard clause 驗證檔案存在)"""
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard interface not found. Please verify web/ directory.",
        )
    return FileResponse(index_file)


@router.get("/api/v1/config/logs", tags=["Config"])
async def get_log_configuration():
    """獲取當前 operations 日誌設定檔內容與解析狀態"""
    raw_text = ""
    if op_logger.config_path.exists():
        try:
            raw_text = op_logger.config_path.read_text(encoding="utf-8")
        except Exception as e:
            raw_text = f"// Error reading config: {e}"

    return {
        "config_path": str(op_logger.config_path),
        "parsed_settings": op_logger.config,
        "raw_config": raw_text,
    }


@router.websocket("/ws/logs")
async def websocket_logs_endpoint(websocket: WebSocket):
    """
    即時操作審計日誌推播 WebSocket 端點
    建立連線後優先推送當日歷史最新紀錄，並持續監聽廣播廣播新日誌
    """
    await websocket.accept()
    queue = op_logger.subscribe()

    # 1. 優先回放當日最近 50 筆歷史操作紀錄
    recent_logs = op_logger.get_recent_logs(limit=50)
    for log_entry in recent_logs:
        try:
            await websocket.send_text(log_entry)
        except Exception:
            break

    # 2. 持續推播即時產生的日誌事件
    try:
        while True:
            log_line = await queue.get()
            # Guard clause: 收到停機哨兵訊號，立刻終止連線迴圈
            if log_line is None:
                break
            await websocket.send_text(log_line)
    except (WebSocketDisconnect, asyncio.CancelledError):
        # 捕捉客戶端離線與服務關閉時之協程取消，防止 ASGI 拋出未捕獲的 CancelledError
        pass
    except Exception as e:
        logger.debug(f"WebSocket 客戶端連線中斷: {type(e).__name__}: {e}")
    finally:
        op_logger.unsubscribe(queue)
        try:
            await websocket.close()
        except Exception:
            pass
