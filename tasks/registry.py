import importlib
import inspect
import pkgutil
from typing import Type
from tasks.base import BaseTask
from core.logger import logger


class TaskRegistry:
    """
    可插拔任務註冊中心
    支援動態載入、擴充、停用與即時結構自省 (Schema Introspection)
    """

    def __init__(self) -> None:
        self._tasks: dict[str, BaseTask] = {}

    def register(self, task: BaseTask) -> None:
        """註冊新任務插件"""
        name = task.metadata.name
        if name in self._tasks:
            logger.warning(f"任務 [{name}] 已存在，將進行覆寫更新")
        self._tasks[name] = task
        logger.info(f"任務插件註冊成功: [{name}] v{task.metadata.version}")

    def unregister(self, name: str) -> bool:
        """卸載指定任務插件 (Guard Clause 驗證存在性)"""
        if name not in self._tasks:
            return False
        del self._tasks[name]
        logger.info(f"任務插件已卸載: [{name}]")
        return True

    def get(self, name: str) -> BaseTask | None:
        """取得指定任務實體 (Guard clause)"""
        return self._tasks.get(name)

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """動態啟用/停用指定任務"""
        task = self.get(name)
        if not task:
            return False
        task.metadata.enabled = enabled
        logger.info(f"任務 [{name}] 狀態變更為: {'啟用' if enabled else '停用'}")
        return True

    def list_tasks(self) -> list[dict]:
        """列出所有已註冊任務與其輸入參數之 JSON Schema"""
        task_list = []
        for name, task in self._tasks.items():
            schema = {}
            if hasattr(task.param_model, "model_json_schema"):
                schema = task.param_model.model_json_schema()

            task_list.append({
                "metadata": task.metadata.model_dump(),
                "input_schema": schema,
            })
        return task_list

    def auto_discover(self, package_name: str = "tasks.builtin") -> None:
        """自動掃描指定模組套件內的所有 BaseTask 衍生類別並完成註冊"""
        try:
            package = importlib.import_module(package_name)
        except ImportError as e:
            logger.error(f"[ERROR_SUMMARY] 無法載入模組套件 {package_name}: {type(e).__name__}: {e}")
            return

        for _, modname, _ in pkgutil.iter_modules(package.__path__):
            full_module_name = f"{package_name}.{modname}"
            try:
                module = importlib.import_module(full_module_name)
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    # 篩選繼承自 BaseTask 且非抽象基類本身的具體實作
                    if issubclass(obj, BaseTask) and obj is not BaseTask:
                        try:
                            instance = obj()
                            self.register(instance)
                        except Exception as init_err:
                            logger.error(f"[ERROR_SUMMARY] 初始化任務類別 {obj.__name__} 失敗: {type(init_err).__name__}: {init_err}")
            except Exception as mod_err:
                logger.error(f"[ERROR_SUMMARY] 載入任務模組 {full_module_name} 失敗: {type(mod_err).__name__}: {mod_err}")


# 全域單例
task_registry = TaskRegistry()
