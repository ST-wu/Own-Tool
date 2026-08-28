---
name: git_diff_compliance
description: Analyze git diff to ensure changes are minimal and compliant with optimization rules.
---

# Git 變更合規檢測技能

當你面臨以下情境時，應使用本技能提供的工具：
1. 在開發任務結束後，準備提交變更前。
2. 需要核對變更是否符合 `Git 變更最小化 (Git Diff Minimization)` 規範。

## 使用方法

執行以下指令：
```powershell
python d:/Agent/Tools/.agents/skills/git_diff_compliance/scripts/check_git_diff.py
```

該工具會：
- 執行 `git diff`。
- 分析目前修改的程式碼行數與異動檔案。
- 若發現有大規模非必要重構、格式重排、或變更檔案過多，會發出警告，指引 AI 精簡程式碼以符合變更最小化原則。
