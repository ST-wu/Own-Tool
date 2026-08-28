---
name: universal_test_throttler
description: Run multi-language tests and throttle output log, showing only failures.
---

# 通用測試日誌節流技能

當你面臨以下情境時，應使用本技能提供的工具：
1. 在多語言專案中執行單元測試。
2. 需要避免大量測試成功的冗長日誌撐爆控制台或 Token 空間。

## 使用方法

執行以下指令：
```powershell
python d:/Agent/Tools/.agents/skills/universal_test_throttler/scripts/run_test.py <path_to_test_file>
```

該工具會：
- 依檔案類型自動呼叫該語言的單元測試框架（如 `pytest`、`npm test`、`dotnet test`）。
- 實施日誌節流：若全部通過，僅輸出極簡的 `All tests passed`；若有失敗，則智慧過濾只輸出失敗的測試案例與堆疊追蹤（包含 `[DEBUG_TRACE]` 訊息）。
