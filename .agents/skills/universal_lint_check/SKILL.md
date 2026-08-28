---
name: universal_lint_check
description: Check multi-language file syntax and fix encoding issues (UTF-8/CP950)
---

# 通用編碼與語法預檢技能

當你面臨以下情境時，應使用本技能提供的工具：
1. 修改或執行任何程式語言檔案（如 Python、C#、JS、JSON 等），且懷疑其有編碼問題。
2. 進行大範圍修改前，想快速檢查程式碼是否有語法結構錯誤。

## 使用方法

執行以下指令：
```powershell
python d:/Agent/Tools/.agents/skills/universal_lint_check/scripts/check_code.py <path_to_code_file>
```

該工具會：
- 自動偵測並將非 UTF-8（如 CP950）編碼轉換為 UTF-8，並保留 `.bak` 備份。
- 依檔案類型（.py、.js、.json、.cs）自動調用輕量檢測工具（如 `py_compile`、`json` 解析器、或嘗試調用系統的 `eslint`、`dotnet build`），指出具體語法出錯行號。
