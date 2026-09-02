# 📚 題庫儲存與擴充規格說明 (Question Bank Ingestion Specification)

本目錄 (`tools/exam_simulator/data/question_banks/`) 為模擬測驗系統的**可插拔式題庫集中管理區**。
系統具備**全自動動態探索機制**，只要在本目錄下放入符合規範的 `*.json` 檔案（例如 `az-900.json`, `dp-100.json`），系統無須重啟或修改程式碼，即可在 Web 控制台動態呈現該科目。

---

## 🎯 題庫檔案命名規範
- 檔名建議採用英文小寫與連字號，作為題庫唯一識別碼（Bank ID），例如：
  - `ai-103.json` -> 題庫 ID 為 `ai-103`
  - `az-900.json` -> 題庫 ID 為 `az-900`
  - `python-advanced.json` -> 題庫 ID 為 `python-advanced`

---

## 📋 JSON 資料結構與欄位定義

題庫檔案根結構為一組題目物件陣列 (`[ { ... }, { ... } ]`)，每個題目支援以下欄位：

| 欄位名稱 | 型別 | 必填 | 說明 |
| :--- | :--- | :---: | :--- |
| `id` | `int` | 是 | 題目唯一序號 (從 1 開始遞增) |
| `topic` | `string` | 否 | 主題領域分類標籤 (如 `"Topic 1"`, `"Architecture"`)，用於前端領域篩選 |
| `type` | `string` | 是 | 題型識別碼：`single_choice` (單選)、`multiple_choice` (複選)、`drop_down` (下拉選單)、`case_study` (案例題) |
| `question` | `string` | 是 | 題目文本內容，支援換行符號 `\n` |
| `options` | `list[string]` | 條件 | 選項陣列 (適用單選與複選題，如 `["A. 選項內容", "B. 選項內容"]`) |
| `answer` | `list[int]` | 是 | 正確答案索引陣列 (0-indexed)。單選題如 `[1]` (表示 B)；複選題如 `[0, 2]` (表示 A, C) |
| `explanation` | `string` | 否 | 詳細答案解析與觀念說明 |
| `dropdowns` | `list[object]` | 條件 | **僅下拉選單題 (`drop_down`) 專用**。定義各題空欄的 placeholder、個別選項清單與答案索引 |
| `case_study_title` | `string` | 否 | **僅案例題 (`case_study`) 專用**。情境案例標題 (如 `"Case Study Scenario · Contoso, Ltd"`) |

---

## 💡 各題型 JSON 撰寫模板

### 1. 單選題 (Single Choice)
```json
{
  "id": 1,
  "topic": "Topic 1",
  "type": "single_choice",
  "question": "What is the primary purpose of Azure AI Search in an agentic workflow?",
  "options": [
    "A. Model training",
    "B. Retrieval-Augmented Generation (RAG) knowledge retrieval",
    "C. Real-time video rendering",
    "D. Network load balancing"
  ],
  "answer": [1],
  "explanation": "Azure AI Search acts as the vector/hybrid search engine providing relevant contextual data for RAG pipelines."
}
```

### 2. 複選題 (Multiple Choice)
```json
{
  "id": 2,
  "topic": "Security & Compliance",
  "type": "multiple_choice",
  "question": "Which TWO components are essential for securing generative AI agents against prompt injection attacks?\nNOTE: Each correct selection is worth one point.",
  "options": [
    "A. Prompt Shields",
    "B. GPU Overclocking",
    "C. Groundedness Detection",
    "D. DNS Load Balancing"
  ],
  "answer": [0, 2],
  "explanation": "Prompt Shields mitigate direct and indirect prompt injection attacks, while Groundedness detection ensures model responses are derived from trusted sources."
}
```

### 3. 下拉填空題 (Drop-Down Selection)
```json
{
  "id": 3,
  "topic": "Model Deployment",
  "type": "drop_down",
  "question": "You need to configure model deployment for Agent1.\n\nAnswer Area\nDeployment type: [Box 1]\nVersion update policy: [Box 2]",
  "options": [],
  "answer": [],
  "explanation": "Select Standard for dynamic throughput scaling, and opt out of automatic upgrades for stability.",
  "dropdowns": [
    {
      "placeholder": "[Box 1]",
      "options": ["Standard", "Global Standard", "Provisioned"],
      "answer": 0
    },
    {
      "placeholder": "[Box 2]",
      "options": [
        "Once current version expires",
        "Opt out of automatic model version upgrades",
        "Upgrade when new default is available"
      ],
      "answer": 1
    }
  ]
}
```

### 4. 案例情境題 (Case Study)
```json
{
  "id": 4,
  "topic": "Case Study · Contoso Ltd",
  "type": "single_choice",
  "case_study_title": "Case Study Scenario · Contoso, Ltd (Healthcare Division)",
  "question": "Based on the Contoso compliance requirements, which encryption method must be used at rest?",
  "options": [
    "A. Platform-managed keys",
    "B. Customer-managed keys (CMK) with Azure Key Vault HSM",
    "C. Unencrypted blob storage",
    "D. Symmetric XOR encoding"
  ],
  "answer": [1],
  "explanation": "Healthcare compliance requires Customer-Managed Keys (CMK) backed by Hardware Security Modules (HSM)."
}
```

---

## 🤖 提示詞模板 (Prompt Template for AI Generation)

當您想請外部 AI / Agent 協助將原始考題轉換為本專案標準題庫 JSON 時，可直接複製以下提示詞：

```text
請將以下考題轉換為符合標準規範的 JSON 陣列格式：
1. 輸出必須為標準 JSON 陣列，不包含任何 Markdown 標記外的多餘註釋。
2. 支援 single_choice, multiple_choice, drop_down, case_study 題型。
3. answer 為 0-indexed 陣列 (例如 A 為 0, B 為 1)。
4. 若為下拉選單題，請在 dropdowns 陣列中定義 placeholder、options 與 answer。
5. 請提供詳盡的 explanation (中文或英文解析)。
```
