import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Type
from pydantic import BaseModel, Field
from playwright.async_api import BrowserContext, Page
from core.browser import browser_manager
from core.logger import logger


class TaskMetadata(BaseModel):
    """任務元資料模型"""
    name: str = Field(..., description="任務唯一標識名稱")
    description: str = Field("", description="任務功能詳細說明")
    version: str = Field("1.0.0", description="任務語意化版本號")
    author: str = Field("System", description="任務開發者")
    tags: list[str] = Field(default_factory=list, description="任務分類標籤")
    enabled: bool = Field(True, description="任務是否啟用")


class TaskExecutionResult(BaseModel):
    """任務執行結果標準輸出模型"""
    task_name: str
    success: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    failure_artifact_path: str | None = None
    execution_time_ms: float
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())


class BaseTask(ABC):
    """
    可擴充 Playwright 任務抽象基類
    所有新任務皆繼承自此類別，享有自動生命週期管理、沙盒隔離與異常畫面錄製
    """

    metadata: TaskMetadata
    param_model: Type[BaseModel] = BaseModel

    @abstractmethod
    async def run(
        self,
        page: Page,
        context: BrowserContext,
        params: BaseModel,
    ) -> dict[str, Any]:
        """
        核心業務自動化邏輯 (由各任務插件自行實作)
        :param page: 已就緒的獨立沙盒頁面
        :param context: 獨立的瀏覽器 Context
        :param params: 經 Pydantic 檢驗過之輸入參數
        :return: 任務自訂回傳資料字典
        """
        pass

    async def execute(self, raw_params: dict[str, Any] | BaseModel | None = None) -> TaskExecutionResult:
        """
        統包執行入口：負責參數檢驗、Context 分配、計時與異常保護
        """
        # Guard clause: 檢查啟用狀態
        if not self.metadata.enabled:
            return TaskExecutionResult(
                task_name=self.metadata.name,
                success=False,
                error=f"Task '{self.metadata.name}' is currently disabled",
                execution_time_ms=0.0,
            )

        # 參數驗證 (Guard clause)
        try:
            if isinstance(raw_params, self.param_model):
                validated_params = raw_params
            elif isinstance(raw_params, dict):
                validated_params = self.param_model.model_validate(raw_params)
            else:
                validated_params = self.param_model()
        except Exception as e:
            logger.warning(f"[PARAM_VALIDATION_FAILED] 任務 {self.metadata.name} 參數無效: {e}")
            return TaskExecutionResult(
                task_name=self.metadata.name,
                success=False,
                error=f"Parameter validation failed: {str(e)}",
                execution_time_ms=0.0,
            )

        start_time = asyncio.get_event_loop().time()
        active_page: Page | None = None
        artifact_path: str | None = None

        try:
            async with browser_manager.get_isolated_context() as context:
                active_page = await context.new_page()
                result_data = await self.run(active_page, context, validated_params)
                elapsed = round((asyncio.get_event_loop().time() - start_time) * 1000, 2)
                return TaskExecutionResult(
                    task_name=self.metadata.name,
                    success=True,
                    data=result_data,
                    execution_time_ms=elapsed,
                )
        except Exception as e:
            elapsed = round((asyncio.get_event_loop().time() - start_time) * 1000, 2)
            logger.error(f"[ERROR_SUMMARY] 任務 {self.metadata.name} 執行失敗: {type(e).__name__}: {e}")
            # 捕獲異常當下畫面
            if active_page:
                artifact_path = await browser_manager.capture_failure_artifact(active_page, self.metadata.name)

            return TaskExecutionResult(
                task_name=self.metadata.name,
                success=False,
                error=f"{type(e).__name__}: {str(e)}",
                failure_artifact_path=artifact_path,
                execution_time_ms=elapsed,
            )

        # 若無 context 生成，視為無法取得瀏覽器資源
        return TaskExecutionResult(
            task_name=self.metadata.name,
            success=False,
            error="Failed to acquire browser context",
            execution_time_ms=0.0,
        )
