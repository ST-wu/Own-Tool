---
name: agent_auditor
description: 診斷 Agent 行為安全與弱點的審計工具。可在每次編輯檔案或執行重要指令後，執行此工具進行自我行為診斷，以防違反備份守則、Token 節流或產生依賴導入崩潰。
---

# Agent 行為審計與自我診斷工具 (AgentAuditor)

此 Skill 可讓 Agent 在每次修改程式碼後主動執行自我行為診斷，確保符合本機工作區的核心優化規則（AGENTS.md）。

## 運作與呼叫機制
在修改了工作區程式碼後，主動執行以下命令進行自我審計：
```bash
python d:/Agent/Tools/.agents/skills/agent_auditor/scripts/auditor.py --conv-id <ConversationID> --output C:/Users/U/.gemini/antigravity-ide/brain/<ConversationID>/agent_diagnosis_report.md
```
若得分低於 90 分，應立即查閱生成的報告並就地修正違規行為。
