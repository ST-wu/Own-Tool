from typing import Any
from pydantic import BaseModel, Field


class RunTaskRequest(BaseModel):
    """執行任務請求模型"""
    params: dict[str, Any] = Field(default_factory=dict, description="傳入該任務之自訂參數字典")


class TaskStatusToggleRequest(BaseModel):
    """任務狀態開關請求模型"""
    enabled: bool = Field(..., description="是否啟用該任務")


class HealthResponse(BaseModel):
    """健康診斷響應模型"""
    service: str = "playwright-service"
    status: str
    latency_ms: float | None = None
    browser_connected: bool = False
    available_permits: int = 0
    error: str | None = None


class StandardResponse(BaseModel):
    """通用成功響應模型"""
    success: bool
    message: str
    data: Any = None
