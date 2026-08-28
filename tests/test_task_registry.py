import pytest
from pydantic import BaseModel
from playwright.async_api import BrowserContext, Page
from tasks.base import BaseTask, TaskMetadata
from tasks.registry import TaskRegistry


class DummyParams(BaseModel):
    name: str = "tester"


class DummyTask(BaseTask):
    metadata = TaskMetadata(
        name="dummy_task",
        description="Dummy test task",
        version="1.0.0",
        enabled=True,
    )
    param_model = DummyParams

    async def run(self, page: Page, context: BrowserContext, params: DummyParams) -> dict:
        return {"greeting": f"Hello {params.name}"}


def test_registry_register_and_get():
    """驗證任務註冊、查詢與刪除機制"""
    registry = TaskRegistry()
    dummy = DummyTask()

    # 註冊
    registry.register(dummy)
    assert registry.get("dummy_task") is not None

    # 列出任務並驗證 Schema
    task_list = registry.list_tasks()
    assert len(task_list) == 1
    assert task_list[0]["metadata"]["name"] == "dummy_task"
    assert "properties" in task_list[0]["input_schema"]

    # 停用
    registry.set_enabled("dummy_task", False)
    assert registry.get("dummy_task").metadata.enabled is False

    # 卸載
    assert registry.unregister("dummy_task") is True
    assert registry.get("dummy_task") is None


def test_registry_auto_discover():
    """驗證自動探索機制能正常掃描模組套件而無異常"""
    registry = TaskRegistry()
    registry.auto_discover("tasks.builtin")
    # 當前 builtin 為純淨目錄，掃描應安全完成且不拋出例外
    assert isinstance(registry.list_tasks(), list)


@pytest.mark.asyncio
async def test_disabled_task_execution_rejection():
    """驗證停用狀態之任務被直接拒絕執行"""
    dummy = DummyTask()
    dummy.metadata.enabled = False
    result = await dummy.execute({"name": "test"})
    assert result.success is False
    assert "disabled" in result.error
