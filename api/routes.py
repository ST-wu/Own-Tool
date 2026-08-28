from fastapi import APIRouter, Depends, HTTPException, status
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


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def get_health_status() -> HealthResponse:
    """系統核心與 Playwright 渲染引擎探活檢測端點"""
    health_data = await browser_manager.check_health()
    op_logger.log("API:GET_HEALTH", "DEBUG", {"status": health_data.get("status")})
    return HealthResponse(
        service="playwright-service",
        status=health_data.get("status", "unknown"),
        latency_ms=health_data.get("latency_ms"),
        browser_connected=health_data.get("browser_connected", False),
        available_permits=health_data.get("available_permits", 0),
        error=health_data.get("error"),
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
