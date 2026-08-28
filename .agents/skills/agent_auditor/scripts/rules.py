import os
import re
import ast
import json
import subprocess
from typing import Dict, List, Any, Tuple

class AuditRule:
    """審計規則基類"""
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description

    def audit(self, transcript: List[Dict[str, Any]], workspace_dir: str) -> Dict[str, Any]:
        raise NotImplementedError

class BackupRule(AuditRule):
    """
    備份規則合規審計 (Backup Protocol Check)
    - 編輯檔案前是否有建立 .bak 備份
    - 任務完成後是否有清除 .bak 備份
    """
    def __init__(self):
        super().__init__(
            "備份安全防護審計",
            "檢查修改代碼前是否建立了 .bak 備份，且在完成測試後是否主動清除備份檔。"
        )

    def audit(self, transcript: List[Dict[str, Any]], workspace_dir: str) -> Dict[str, Any]:
        modified_files = set()
        backups_created = set()
        warnings = []
        
        # 1. 記錄每個檔案的第一個操作工具，用以判斷是否為新創檔案
        first_op = {}
        for step in transcript:
            tool_calls = step.get("tool_calls", [])
            for call in tool_calls:
                name = call.get("name")
                args = call.get("args", {})
                target_file = args.get("TargetFile") or args.get("AbsolutePath")
                if target_file:
                    target_file = os.path.normpath(target_file.strip('"'))
                    if target_file not in first_op:
                        first_op[target_file] = name

        # 2. 解析 Transcript 記錄的工具調用，篩選受審計的代碼檔案
        code_extensions = [".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".rs", ".go", ".c", ".cpp", ".h", ".cs", ".sh", ".ps1"]
        for step in transcript:
            tool_calls = step.get("tool_calls", [])
            for call in tool_calls:
                name = call.get("name")
                args = call.get("args", {})
                
                # 偵測檔案修改動作
                if name in ["replace_file_content", "multi_replace_file_content", "write_to_file"]:
                    target_file = args.get("TargetFile")
                    if target_file:
                        target_file = os.path.normpath(target_file.strip('"'))
                        
                        # 排除備份檔與系統檔本身，並且只審計代碼檔案
                        if not target_file.endswith(".bak") and ".system_generated" not in target_file:
                            ext = os.path.splitext(target_file)[1].lower()
                            if ext in code_extensions:
                                modified_files.add(target_file)
                
                # 偵測備份檔創建動作
                if name == "write_to_file":
                    target_file = args.get("TargetFile")
                    if target_file:
                        target_file = os.path.normpath(target_file.strip('"'))
                        if target_file.endswith(".bak"):
                            backups_created.add(target_file)

        # 3. 檢測修改的檔案是否有備份檔
        untracked_files = set()
        try:
            res = subprocess.run(["git", "status", "--porcelain"], cwd=workspace_dir, capture_output=True, text=True, check=True)
            for line in res.stdout.splitlines():
                if line.startswith("??") or line.startswith("A "):
                    rel_path = line[3:].strip()
                    abs_path = os.path.normpath(os.path.join(workspace_dir, rel_path))
                    untracked_files.add(abs_path)
        except Exception:
            pass

        unbacked_up = []
        for f in modified_files:
            # 如果是 Git 未追蹤的新檔案，或是日誌中第一個動作就是創建該檔案，則跳過備份檢測
            if f in untracked_files or first_op.get(f) == "write_to_file":
                continue
            bak_path = f + ".bak"
            if bak_path not in backups_created:
                # 檢查實體檔案系統是否已有 .bak
                if not os.path.exists(bak_path):
                    unbacked_up.append(f)

        if unbacked_up:
            for f in unbacked_up:
                warnings.append({
                    "severity": "HIGH",
                    "message": f"修改檔案 {os.path.basename(f)} 前未建立同級 .bak 備份，違反安全防護守則。"
                })

        # 4. 檢查工作區是否殘留 .bak 檔案
        uncleared_bak = []
        for root, dirs, files in os.walk(workspace_dir):
            # 排除 .git, .gemini 等隱藏目錄
            dirs[:] = [d for d in dirs if not d.startswith('.') and d != 'node_modules']
            for file in files:
                if file.endswith(".bak"):
                    uncleared_bak.append(os.path.join(root, file))

        if uncleared_bak:
            for bak in uncleared_bak:
                warnings.append({
                    "severity": "MEDIUM",
                    "message": f"工作區殘留備份檔 {os.path.basename(bak)}，完成修改與測試後未主動清除。"
                })

        score = max(0, 100 - len(warnings) * 15)
        return {
            "name": self.name,
            "description": self.description,
            "score": score,
            "passed": score >= 80,
            "warnings": warnings,
            "details": {
                "modified_files": list(modified_files),
                "backups_created": list(backups_created),
                "remaining_backups": uncleared_bak
            }
        }

class TokenWasteRule(AuditRule):
    """
    Token 節流審計 (Token Conservation Check)
    - view_file 是否過度讀取大檔案而未使用行數限制
    """
    def __init__(self):
        super().__init__(
            "Token 節流審計",
            "檢查是否無行數限制 (StartLine/EndLine) 讀取大檔案，造成輸入 Token 浪費。"
        )

    def audit(self, transcript: List[Dict[str, Any]], workspace_dir: str) -> Dict[str, Any]:
        warnings = []
        total_view_calls = 0
        waste_calls = 0

        for step_idx, step in enumerate(transcript):
            tool_calls = step.get("tool_calls", [])
            for call in tool_calls:
                name = call.get("name")
                args = call.get("args", {})
                
                if name == "view_file":
                    total_view_calls += 1
                    path = args.get("AbsolutePath")
                    if path:
                        path = os.path.normpath(path.strip('"'))
                    start = args.get("StartLine")
                    end = args.get("EndLine")

                    # 如果沒有行數限制，且檔案行數可能大於 100
                    if path and (start is None or end is None):
                        # 實體檢測檔案行數
                        if os.path.exists(path):
                            try:
                                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                                    lines = f.readlines()
                                if len(lines) > 100:
                                    waste_calls += 1
                                    warnings.append({
                                        "severity": "LOW",
                                        "message": f"第 {step_idx} 步：讀取 {os.path.basename(path)} 共 {len(lines)} 行，未使用 StartLine/EndLine 限制，導致 Token 浪費。"
                                    })
                            except Exception:
                                pass

        score = 100
        if total_view_calls > 0:
            score = int((1 - (waste_calls / total_view_calls)) * 100)

        return {
            "name": self.name,
            "description": self.description,
            "score": score,
            "passed": score >= 85,
            "warnings": warnings,
            "details": {
                "total_view_calls": total_view_calls,
                "waste_calls": waste_calls
            }
        }

class ToolLoopRule(AuditRule):
    """
    無效嘗試死迴圈審計 (Redundancy Loop Check)
    - 偵測是否在同一錯誤上連續調用工具失敗且無就地修正
    """
    def __init__(self):
        super().__init__(
            "重複無效嘗試審計",
            "偵測 Agent 是否陷入死迴圈，反覆以類似參數調用相同的失敗指令或錯誤 URL。"
        )

    def audit(self, transcript: List[Dict[str, Any]], workspace_dir: str) -> Dict[str, Any]:
        warnings = []
        consecutive_failures = []
        loop_detected = False

        for step_idx, step in enumerate(transcript):
            status = step.get("status", "DONE")
            tool_calls = step.get("tool_calls", [])
            content = step.get("content", "")

            is_failure = (status == "ERROR" or "error" in content.lower() or "failed" in content.lower())
            
            for call in tool_calls:
                name = call.get("name")
                args = call.get("args", {})
                
                call_fingerprint = f"{name}:{hash(json.dumps(args, sort_keys=True))}"
                
                if is_failure:
                    consecutive_failures.append((step_idx, call_fingerprint, name, args))
                else:
                    consecutive_failures = []

                if len(consecutive_failures) >= 3:
                    tool_names = [f[2] for f in consecutive_failures]
                    if len(set(tool_names)) == 1:
                        loop_detected = True
                        steps_str = ", ".join(str(f[0]) for f in consecutive_failures)
                        warnings.append({
                            "severity": "HIGH",
                            "message": f"在步驟 {steps_str} 中，反覆調用 {tool_names[0]} 工具失敗，顯示 Agent 缺乏就地容錯與自我修正能力。"
                        })
                        consecutive_failures = []

        score = 100 - (len(warnings) * 20)
        score = max(0, score)

        return {
            "name": self.name,
            "description": self.description,
            "score": score,
            "passed": not loop_detected,
            "warnings": warnings,
            "details": {
                "loop_detected": loop_detected
            }
        }

class DependencySafetyRule(AuditRule):
    """
    未聲明依賴安全審計 (Dependency Safety Check)
    - 檢查代碼修改是否引入了未在 package.json 或 requirements.txt 聲明的外部依賴
    """
    def __init__(self):
        super().__init__(
            "未聲明依賴審計",
            "檢查代碼中引入的新模組是否未寫入專案環境設定檔，防止運行時出現 ModuleNotFoundError。"
        )

    def audit(self, transcript: List[Dict[str, Any]], workspace_dir: str) -> Dict[str, Any]:
        warnings = []
        modified_files = set()

        for step in transcript:
            tool_calls = step.get("tool_calls", [])
            for call in tool_calls:
                if call.get("name") in ["replace_file_content", "multi_replace_file_content", "write_to_file"]:
                    tf = call.get("args", {}).get("TargetFile")
                    if tf:
                        tf = os.path.normpath(tf.strip('"'))
                        if os.path.exists(tf) and not tf.endswith(".bak") and ".system_generated" not in tf:
                            modified_files.add(tf)

        declared_dependencies = set()
        
        req_path = os.path.join(workspace_dir, "requirements.txt")
        if os.path.exists(req_path):
            try:
                with open(req_path, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            parts = re.split(r'[=<>~]', line)
                            declared_dependencies.add(parts[0].strip().lower())
            except Exception:
                pass

        pkg_path = os.path.join(workspace_dir, "package.json")
        if os.path.exists(pkg_path):
            try:
                with open(pkg_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for dep_type in ["dependencies", "devDependencies"]:
                        for dep in data.get(dep_type, {}).keys():
                            declared_dependencies.add(dep.lower())
            except Exception:
                pass

        for fpath in modified_files:
            if fpath.endswith(".py"):
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        tree = ast.parse(f.read(), filename=fpath)
                    
                    for node in ast.walk(tree):
                        imported_module = None
                        if isinstance(node, ast.Import):
                            for alias in node.names:
                                imported_module = alias.name.split('.')[0]
                        elif isinstance(node, ast.ImportFrom):
                            if node.level == 0 and node.module:
                                imported_module = node.module.split('.')[0]
                            elif node.level > 0:
                                # 相對引入 (from . import xxx) 屬本地模組直接跳過
                                imported_module = None
                        
                        if imported_module:
                            # 檢測是否為與該檔案同目錄的本地 .py 模組
                            file_dir = os.path.dirname(fpath)
                            is_local_sibling = (
                                os.path.exists(os.path.join(file_dir, imported_module + ".py")) or
                                os.path.exists(os.path.join(file_dir, imported_module))
                            )
                            if not is_local_sibling and self._is_third_party_python(imported_module, workspace_dir):
                                if imported_module.lower() not in declared_dependencies:
                                    warnings.append({
                                        "severity": "HIGH",
                                        "message": f"檔案 {os.path.basename(fpath)} 引入了外部庫 '{imported_module}'，但未在 requirements.txt 中聲明。"
                                    })
                except Exception:
                    pass
            elif fpath.endswith((".js", ".jsx", ".ts", ".tsx")):
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                    
                    imports = re.findall(r'from\s+[\'"]([^\.\/][^\'"]*)[\'"]', content)
                    requires = re.findall(r'require\(\s*[\'"]([^\.\/][^\'"]*)[\'"]\s*\)', content)
                    
                    all_imports = set(imports + requires)
                    for imp in all_imports:
                        node_stdlib = ["fs", "path", "os", "crypto", "http", "https", "child_process", "util", "events"]
                        base_imp = imp.split('/')[0]
                        if base_imp not in node_stdlib:
                            if base_imp.lower() not in declared_dependencies:
                                warnings.append({
                                    "severity": "HIGH",
                                    "message": f"檔案 {os.path.basename(fpath)} 引入了 npm 套件 '{base_imp}'，但未在 package.json 聲明。"
                                })
                except Exception:
                    pass

        score = max(0, 100 - len(warnings) * 20)
        return {
            "name": self.name,
            "description": self.description,
            "score": score,
            "passed": score >= 80,
            "warnings": warnings,
            "details": {}
        }

    def _is_third_party_python(self, module_name: str, workspace_dir: str) -> bool:
        import sys
        if module_name in sys.builtin_module_names:
            return False
        if os.path.exists(os.path.join(workspace_dir, module_name)) or \
           os.path.exists(os.path.join(workspace_dir, module_name + ".py")):
            return False
        
        # 建全的標準庫白名單，涵蓋常規使用的內建模組
        std_libs = [
            "json", "os", "sys", "re", "math", "datetime", "subprocess", "shutil",
            "typing", "collections", "hashlib", "time", "ast", "fnmatch", "glob",
            "argparse", "logging", "pathlib", "threading", "multiprocessing",
            "functools", "itertools", "io", "copy", "random", "string", "struct",
            "base64", "urllib", "http", "socket", "email", "html", "xml",
            "csv", "sqlite3", "unittest", "contextlib", "dataclasses", "enum",
            "abc", "weakref", "gc", "traceback", "inspect", "importlib", "pkgutil",
            "platform", "signal", "tempfile", "zipfile", "tarfile", "gzip",
            "warnings", "pprint", "textwrap", "difflib", "decimal", "fractions",
        ]
        if module_name in std_libs:
            return False

        return True

class TroubleshootingChaosRule(AuditRule):
    """
    除錯效率與混亂度審計 (Troubleshooting Chaos Check)
    - 檢測出錯後，Agent 是否花費多個回合才修復，或盲目修改多個無關檔案。
    """
    def __init__(self):
        super().__init__(
            "除錯效率與定位能力審計",
            "分析出錯後的修正路徑，檢測 Agent 是否存在盲目試錯、越改越亂的除錯定位弱點。"
        )

    def audit(self, transcript: List[Dict[str, Any]], workspace_dir: str) -> Dict[str, Any]:
        warnings = []
        fail_step = -1
        steps_to_fix = 0
        files_modified_during_fix = set()
        chaos_events = 0

        for step_idx, step in enumerate(transcript):
            status = step.get("status", "DONE")
            content = step.get("content", "")
            tool_calls = step.get("tool_calls", [])

            is_failure = (status == "ERROR" or "error" in content.lower() or "failed" in content.lower())

            if fail_step != -1:
                # 處於修復階段
                steps_to_fix += 1
                
                # 追蹤修復期間修改的檔案
                for call in tool_calls:
                    if call.get("name") in ["replace_file_content", "multi_replace_file_content", "write_to_file"]:
                        tf = call.get("args", {}).get("TargetFile")
                        if tf:
                            files_modified_during_fix.add(os.path.normpath(tf.strip('"')))

                # 檢測是否修復成功
                if not is_failure and status == "DONE":
                    if steps_to_fix > 2:
                        chaos_events += 1
                        warnings.append({
                            "severity": "HIGH",
                            "message": f"步驟 {fail_step} 發生錯誤後，Agent 花費了多達 {steps_to_fix} 個回合才修復成功，暴露了錯誤定位排除能力較弱的缺點。"
                        })
                    if len(files_modified_during_fix) > 2:
                        chaos_events += 1
                        warnings.append({
                            "severity": "MEDIUM",
                            "message": f"在修復步驟 {fail_step} 的錯誤期間，修改了多達 {len(files_modified_during_fix)} 個不同檔案，顯示除錯範圍過大，存在盲目試錯行為。"
                        })
                    # 重置狀態
                    fail_step = -1
                    steps_to_fix = 0
                    files_modified_during_fix = set()
            else:
                if is_failure:
                    fail_step = step_idx
                    steps_to_fix = 0
                    files_modified_during_fix = set()

        score = max(0, 100 - chaos_events * 25)
        return {
            "name": self.name,
            "description": self.description,
            "score": score,
            "passed": score >= 80,
            "warnings": warnings,
            "details": {}
        }



class DefensiveCodingRule(AuditRule):
    """
    防禦性編程審計 (Defensive Coding Check)
    - 檢測高風險操作（如 json.loads, open, dict 索引）是否包裹了 try-except 異常防護。
    """
    def __init__(self):
        super().__init__(
            "防禦性編程安全審計",
            "檢查高風險的操作（例如 JSON 解析、檔案存取）是否進行了例外安全防護 (try-except)。"
        )

    def audit(self, transcript: List[Dict[str, Any]], workspace_dir: str) -> Dict[str, Any]:
        warnings = []
        modified_files = set()

        for step in transcript:
            for call in step.get("tool_calls", []):
                if call.get("name") in ["replace_file_content", "multi_replace_file_content", "write_to_file"]:
                    tf = call.get("args", {}).get("TargetFile")
                    if tf:
                        tf = os.path.normpath(tf.strip('"'))
                        if os.path.exists(tf) and not tf.endswith(".bak") and ".system_generated" not in tf:
                            modified_files.add(tf)

        unprotected_calls = 0

        for fpath in modified_files:
            if fpath.endswith(".py"):
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
                        tree = ast.parse(f.read(), filename=fpath)

                    # 建立 AST 節點父子關係對照表，用以判斷一個節點是否在 Try 區塊內
                    parent_map = {}
                    for parent in ast.walk(tree):
                        for child in ast.iter_child_nodes(parent):
                            parent_map[child] = parent

                    def is_inside_try(node) -> bool:
                        curr = node
                        while curr in parent_map:
                            curr = parent_map[curr]
                            if isinstance(curr, ast.Try):
                                return True
                        return False

                    # 掃描高風險調用
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Call):
                            func_name = None
                            if isinstance(node.func, ast.Name):
                                func_name = node.func.id
                            elif isinstance(node.func, ast.Attribute):
                                func_name = node.func.attr

                            # json.loads 或 open 是常見崩潰點
                            if func_name in ["loads", "open", "loads_json", "read_file"]:
                                if not is_inside_try(node):
                                    unprotected_calls += 1
                                    warnings.append({
                                        "severity": "MEDIUM",
                                        "message": f"檔案 {os.path.basename(fpath)} 中調用了高風險的 '{func_name}'，但未被 try-except 包裹防護。"
                                    })
                except Exception:
                    pass

        score = max(0, 100 - unprotected_calls * 20)
        return {
            "name": self.name,
            "description": self.description,
            "score": score,
            "passed": score >= 80,
            "warnings": warnings,
            "details": {}
        }
