import ast
import os
from pathlib import Path
from typing import Any
from core.logger import logger
from tools.code_nebula.models import (
    SymbolNode,
    SymbolType,
    DependencyEdge,
    RelationType,
)


class ASTCodeAnalyzer:
    """
    Python AST 靜態代碼語法樹分析器
    專職解析檔案內部符號定義 (Class/Function/Method) 與跨檔案呼叫 (Call/Import/Inherit)
    """

    IGNORE_DIRS = {
        ".venv",
        "venv",
        "__pycache__",
        ".git",
        ".pytest_cache",
        ".agents",
        "node_modules",
        "dist",
        "build",
    }

    def __init__(self, workspace_root: Path | None = None) -> None:
        self.workspace_root = workspace_root or Path(os.getcwd())
        self.symbols: dict[str, SymbolNode] = {}
        self.edges: list[DependencyEdge] = []
        # 模組內部頂層符號索引: { "core.browser": {"BrowserManager": "class", "browser_manager": "instance"} }
        self.module_exports: dict[str, dict[str, str]] = {}
        # 每個檔案的匯入對照表: { file_path: { alias: (full_module, original_name) } }
        self.file_imports: dict[str, dict[str, tuple[str, str]]] = {}
        # 每個檔案的頂層實例變數對照表: { file_path: { var_name: class_name } }
        self.file_instances: dict[str, dict[str, str]] = {}

    def _determine_module_group(self, rel_path: str) -> str:
        """依據相對路徑歸納模組分類群組"""
        parts = rel_path.replace("\\", "/").split("/")
        if len(parts) > 1:
            first = parts[0].lower()
            if first in ("core", "api", "tasks", "tools", "tests", "web", "config"):
                return first
        return "main"

    def _module_name_from_path(self, file_path: Path) -> str:
        """從檔案相對路徑轉為 Python 模組命名 (如 core/browser.py -> core.browser)"""
        try:
            rel = file_path.relative_to(self.workspace_root)
        except ValueError:
            rel = file_path
        parts = list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        return ".".join(parts)

    def _format_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """格式化函數參數簽名"""
        args_list: list[str] = []
        # positional & keyword args
        for arg in node.args.args:
            arg_str = arg.arg
            if arg.annotation:
                arg_str += f": {ast.unparse(arg.annotation)}"
            args_list.append(arg_str)
        if node.args.vararg:
            args_list.append(f"*{node.args.vararg.arg}")
        if node.args.kwarg:
            args_list.append(f"**{node.args.kwarg.arg}")
        
        returns_str = ""
        if node.returns:
            returns_str = f" -> {ast.unparse(node.returns)}"
        
        return f"({', '.join(args_list)}){returns_str}"

    def analyze_directory(self, target_dir: Path | None = None) -> tuple[dict[str, SymbolNode], list[DependencyEdge]]:
        """
        掃描並解析目錄下所有 Python 檔案
        分為兩階段：第一階段收集所有符號定義與 Import；第二階段解析 Call 與關聯連線
        """
        scan_root = target_dir or self.workspace_root
        self.symbols.clear()
        self.edges.clear()
        self.module_exports.clear()
        self.file_imports.clear()
        self.file_instances.clear()

        py_files: list[Path] = []
        for root, dirs, files in os.walk(scan_root):
            # 排除忽略目錄
            dirs[:] = [d for d in dirs if d not in self.IGNORE_DIRS]
            for file in files:
                if file.endswith(".py"):
                    py_files.append(Path(root) / file)

        parsed_asts: dict[str, tuple[Path, str, ast.AST, str]] = {}

        # -------------------------------------------------------------
        # 階段一：解析 AST 建立符號節點與收集 Imports / Instances
        # -------------------------------------------------------------
        for file_path in py_files:
            try:
                rel_path_str = str(file_path.relative_to(self.workspace_root)).replace("\\", "/")
            except ValueError:
                rel_path_str = str(file_path).replace("\\", "/")

            module_name = self._module_name_from_path(file_path)
            module_group = self._determine_module_group(rel_path_str)

            try:
                source_code = file_path.read_text(encoding="utf-8", errors="replace")
                tree = ast.parse(source_code, filename=str(file_path))
                parsed_asts[module_name] = (file_path, rel_path_str, tree, source_code)
            except Exception as e:
                logger.warning(f"[ERROR_SUMMARY] AST 解析檔案失敗 ({rel_path_str}): {type(e).__name__}: {e}")
                continue

            # 建立模組節點
            module_id = f"{module_name}:__module__"
            self.symbols[module_id] = SymbolNode(
                id=module_id,
                name=module_name.split(".")[-1],
                display_name=f"module {module_name}",
                symbol_type=SymbolType.MODULE,
                file_path=rel_path_str,
                line_start=1,
                line_end=len(source_code.splitlines()),
                docstring=ast.get_docstring(tree),
                signature=None,
                module_group=module_group,
                is_external=False,
            )

            # 提取 Imports 與頂層 Instance 賦值
            import_map: dict[str, tuple[str, str]] = {}
            local_instances: dict[str, str] = {}

            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        asname = alias.asname or alias.name
                        import_map[asname] = (alias.name, alias.name)
                elif isinstance(node, ast.ImportFrom):
                    from_module = node.module or ""
                    # 處理相對匯入 (如 from . import config)
                    if node.level > 0:
                        parts = module_name.split(".")
                        base_parts = parts[:-node.level] if len(parts) >= node.level else []
                        if from_module:
                            from_module = ".".join(base_parts + [from_module])
                        else:
                            from_module = ".".join(base_parts)

                    for alias in node.names:
                        asname = alias.asname or alias.name
                        import_map[asname] = (from_module, alias.name)
                elif isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                            try:
                                cls_name = ast.unparse(node.value.func).split(".")[-1]
                                local_instances[target.id] = cls_name
                            except Exception:
                                pass

            self.file_imports[rel_path_str] = import_map
            self.file_instances[rel_path_str] = local_instances
            self.module_exports[module_name] = {}

            # 遍歷 Class 與 Function 定義
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    class_id = f"{module_name}:{node.name}"
                    self.module_exports[module_name][node.name] = "class"
                    self.symbols[class_id] = SymbolNode(
                        id=class_id,
                        name=node.name,
                        display_name=f"class {node.name}",
                        symbol_type=SymbolType.CLASS,
                        file_path=rel_path_str,
                        line_start=node.lineno,
                        line_end=getattr(node, "end_lineno", node.lineno),
                        docstring=ast.get_docstring(node),
                        signature=f"({', '.join(ast.unparse(b) for b in node.bases)})" if node.bases else "()",
                        module_group=module_group,
                        is_external=False,
                    )
                    # 建立 模組 CONTAINS 類別 邊
                    self.edges.append(
                        DependencyEdge(
                            source=module_id,
                            target=class_id,
                            relation=RelationType.CONTAINS,
                            line_number=node.lineno,
                        )
                    )

                    # 類別繼承關聯
                    for base in node.bases:
                        base_name = ast.unparse(base)
                        base_target_id = self._resolve_symbol_id(base_name, import_map, module_name)
                        if base_target_id:
                            self.edges.append(
                                DependencyEdge(
                                    source=class_id,
                                    target=base_target_id,
                                    relation=RelationType.INHERITS,
                                    line_number=node.lineno,
                                )
                            )

                    # 類別內部方法
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            method_type = SymbolType.ASYNC_METHOD if isinstance(item, ast.AsyncFunctionDef) else SymbolType.METHOD
                            method_id = f"{module_name}:{node.name}.{item.name}"
                            self.symbols[method_id] = SymbolNode(
                                id=method_id,
                                name=item.name,
                                display_name=f"{node.name}.{item.name}()",
                                symbol_type=method_type,
                                file_path=rel_path_str,
                                line_start=item.lineno,
                                line_end=getattr(item, "end_lineno", item.lineno),
                                docstring=ast.get_docstring(item),
                                signature=self._format_signature(item),
                                module_group=module_group,
                                is_external=False,
                            )
                            # 類別 CONTAINS 方法 邊
                            self.edges.append(
                                DependencyEdge(
                                    source=class_id,
                                    target=method_id,
                                    relation=RelationType.CONTAINS,
                                    line_number=item.lineno,
                                )
                            )

                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    func_type = SymbolType.ASYNC_FUNCTION if isinstance(node, ast.AsyncFunctionDef) else SymbolType.FUNCTION
                    func_id = f"{module_name}:{node.name}"
                    self.module_exports[module_name][node.name] = "function"
                    self.symbols[func_id] = SymbolNode(
                        id=func_id,
                        name=node.name,
                        display_name=f"def {node.name}()",
                        symbol_type=func_type,
                        file_path=rel_path_str,
                        line_start=node.lineno,
                        line_end=getattr(node, "end_lineno", node.lineno),
                        docstring=ast.get_docstring(node),
                        signature=self._format_signature(node),
                        module_group=module_group,
                        is_external=False,
                    )
                    # 模組 CONTAINS 函數 邊
                    self.edges.append(
                        DependencyEdge(
                            source=module_id,
                            target=func_id,
                            relation=RelationType.CONTAINS,
                            line_number=node.lineno,
                        )
                    )

        # -------------------------------------------------------------
        # 階段二：解析 AST Call 呼叫依賴邊
        # -------------------------------------------------------------
        for module_name, (file_path, rel_path_str, tree, _) in parsed_asts.items():
            import_map = self.file_imports.get(rel_path_str, {})
            self._extract_calls_from_tree(tree, module_name, rel_path_str, import_map)

        # -------------------------------------------------------------
        # 階段三：統計每個節點的 call_count 與 called_by_count
        # -------------------------------------------------------------
        for edge in self.edges:
            if edge.relation == RelationType.CALLS:
                if edge.source in self.symbols:
                    self.symbols[edge.source].call_count += 1
                if edge.target in self.symbols:
                    self.symbols[edge.target].called_by_count += 1

        return self.symbols, self.edges

    def _resolve_symbol_id(
        self,
        expr_name: str,
        import_map: dict[str, tuple[str, str]],
        current_module: str,
        local_instances: dict[str, str] | None = None,
    ) -> str | None:
        """將表達式名稱解析為全域符號 ID (如 browser_manager.start -> core.browser:BrowserManager.start)"""
        # 1. 本地模組內同名定義 (如直接呼叫 local_func)
        local_candidate = f"{current_module}:{expr_name}"
        if local_candidate in self.symbols:
            return local_candidate

        parts = expr_name.split(".")
        root_name = parts[0]

        # 2. 檢查本地實例變數對照表 (如 op_logger = OperationLogger())
        if local_instances and root_name in local_instances and len(parts) > 1:
            class_name = local_instances[root_name]
            method_name = ".".join(parts[1:])
            inst_target_id = f"{current_module}:{class_name}.{method_name}"
            if inst_target_id in self.symbols:
                return inst_target_id

        # 3. 檢查本地類別靜態呼叫 (如 BrowserManager.start)
        if len(parts) > 1:
            class_candidate = f"{current_module}:{parts[0]}.{parts[1]}"
            if class_candidate in self.symbols:
                return class_candidate

        # 4. 檢查 Import 對照表 (如 from core.browser import browser_manager 或 import core.browser)
        if root_name in import_map:
            mod_path, orig_name = import_map[root_name]
            target_mod = mod_path

            if len(parts) == 1:
                # 如 `verify_api_key`
                target_id = f"{target_mod}:{orig_name}"
                if target_id in self.symbols:
                    return target_id
            else:
                # 如 `browser_manager.check_health`
                method_name = ".".join(parts[1:])
                # 嘗試直接比對模組.類別/實例.方法
                for sym_id in self.symbols:
                    if sym_id.startswith(f"{target_mod}:") and sym_id.endswith(f".{method_name}"):
                        return sym_id
                target_id = f"{target_mod}:{orig_name}.{method_name}"
                if target_id in self.symbols:
                    return target_id

        # 5. 嘗試全專案符號名稱比對
        for sym_id, sym_node in self.symbols.items():
            if sym_node.name == parts[-1] and sym_node.symbol_type != SymbolType.MODULE:
                return sym_id

        return None

    def _extract_calls_from_tree(
        self,
        tree: ast.AST,
        module_name: str,
        rel_path_str: str,
        import_map: dict[str, tuple[str, str]],
    ) -> None:
        """遞歸巡檢 AST 提取所有函數內的 Call 呼叫"""

        class CallVisitor(ast.NodeVisitor):
            def __init__(self, outer: "ASTCodeAnalyzer") -> None:
                self.outer = outer
                self.current_caller_id: str | None = None
                self.current_class: str | None = None

            def visit_ClassDef(self, node: ast.ClassDef) -> Any:
                old_class = self.current_class
                self.current_class = node.name
                self.generic_visit(node)
                self.current_class = old_class

            def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
                self._handle_function(node)

            def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
                self._handle_function(node)

            def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
                old_caller = self.current_caller_id
                if self.current_class:
                    self.current_caller_id = f"{module_name}:{self.current_class}.{node.name}"
                else:
                    self.current_caller_id = f"{module_name}:{node.name}"

                self.generic_visit(node)
                self.current_caller_id = old_caller

            def visit_Call(self, node: ast.Call) -> Any:
                if not self.current_caller_id:
                    self.generic_visit(node)
                    return

                callee_name = ""
                try:
                    callee_name = ast.unparse(node.func)
                except Exception:
                    pass

                if callee_name:
                    # 處理 self.method 呼叫
                    if callee_name.startswith("self.") and self.current_class:
                        method_name = callee_name.replace("self.", "", 1)
                        target_id = f"{module_name}:{self.current_class}.{method_name}"
                        if target_id in self.outer.symbols and target_id != self.current_caller_id:
                            self.outer.edges.append(
                                DependencyEdge(
                                    source=self.current_caller_id,
                                    target=target_id,
                                    relation=RelationType.CALLS,
                                    line_number=node.lineno,
                                )
                            )
                    else:
                        local_instances = self.outer.file_instances.get(rel_path_str, {})
                        target_id = self.outer._resolve_symbol_id(callee_name, import_map, module_name, local_instances)
                        if target_id and target_id in self.outer.symbols and target_id != self.current_caller_id:
                            # 避免重複完全相同的邊
                            self.outer.edges.append(
                                DependencyEdge(
                                    source=self.current_caller_id,
                                    target=target_id,
                                    relation=RelationType.CALLS,
                                    line_number=node.lineno,
                                )
                            )
                        elif not target_id and "." not in callee_name and callee_name not in ("print", "len", "str", "int", "isinstance", "type", "range", "list", "dict", "set"):
                            # 記錄輕量級外部/內建符號 (若需要可視化)
                            ext_id = f"builtins:{callee_name}"
                            if ext_id not in self.outer.symbols:
                                self.outer.symbols[ext_id] = SymbolNode(
                                    id=ext_id,
                                    name=callee_name,
                                    display_name=f"{callee_name}()",
                                    symbol_type=SymbolType.EXTERNAL,
                                    file_path=None,
                                    line_start=None,
                                    line_end=None,
                                    docstring=None,
                                    signature=None,
                                    module_group="external",
                                    is_external=True,
                                )
                            self.outer.edges.append(
                                DependencyEdge(
                                    source=self.current_caller_id,
                                    target=ext_id,
                                    relation=RelationType.CALLS,
                                    line_number=node.lineno,
                                )
                            )

                self.generic_visit(node)

        visitor = CallVisitor(self)
        visitor.visit(tree)
