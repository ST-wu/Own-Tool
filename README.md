# Playwright Daemon & Automation Service
> 高可擴充性、高安全性、具備自動化探針與生命週期自癒能力之 Playwright 常駐應用服務。

---

## 🌟 專案核心特色

1. **常駐與生命週期自癒 (Long-Running & Self-Healing)**：
   - 支援常駐 HTTP 服務模式（FastAPI Lifespan）與背景定時排程引擎。
   - 瀏覽器連線斷線自動偵測與無感重啟。
   - 輕量化 `BrowserContext` 沙盒隔離，每個任務獨佔全新 Session，任務結束強制釋放，杜絕記憶體洩漏與 Cookie 污染。
2. **極致擴充性 (Plugin Strategy Architecture)**：
   - 採用插件化設計模式，所有自動化功能均繼承抽象基類 `BaseTask`。
   - **動態自動探索與註冊**：新增、修改或刪除任務只需在 `tasks/` 增減檔案，**無須變動任何底層常駐核心代碼**。
   - 具備即時參數自省（自動產出 Pydantic JSON Schema 供 API 客戶端直接參照）。
3. **安全性防護 (Security by Design)**：
   - 全面啟用 Header API Key 鑑權防護 (`X-API-Key`)，非授權請求提早阻斷。
   - 強型別 Pydantic 輸入參數檢驗，杜絕惡意格式或邊界異常輸入。
   - 限制最大並發數 (`MAX_CONCURRENT_CONTEXTS`)，防止本機運算資源耗盡引發 OOM。
4. **可觀測性與自動化檢測 (Observability & Diagnostics)**：
   - 提供即時 `/health` 探活探針端點（量測 Playwright 渲染延遲與資源可用性）。
   - 任務執行失敗時**自動錄製當下畫面快照** (`artifacts/failures/*.png`)，便於審計排查。
   - 整合 Loguru 結構化輪轉日誌。

---

## 📂 系統目錄與檔案歸類說明

```
d:\Agent\Tools\Playwright/
├── .env.example                  # [設定範本] 環境變數配置範本 (金鑰、埠號、瀏覽器選項)
├── pyproject.toml                # [套件管理] uv / PEP 621 專案宣告與相依套件清單
├── uv.lock                       # [依賴鎖定] 鎖定跨環境安裝之精準版本
├── README.md                     # [專案文檔] 系統架構、檔案歸類與擴充操作手冊
├── config.py                     # [配置中心] 基於 Pydantic-Settings 的強型別設定讀取
├── main.py                       # [系統入口] 服務啟動、FastAPI Lifespan 與 CLI 調度器
│
├── core/                         # ⚙️ 常駐核心引擎 (一般業務開發無需更動)
│   ├── __init__.py
│   ├── browser.py                # 瀏覽器生命週期、Context 池、並發信號控制與自癒機制
│   ├── security.py               # 安全性鑑權依賴 (X-API-Key Guard Clauses)
│   ├── scheduler.py              # 背景週期性排程調度器 (定時巡檢與心跳)
│   └── logger.py                 # Loguru 結構化日誌輸出與每天/大小檔案輪轉配置
│
├── tasks/                        # 🧩 可擴充任務插件目錄 (未來擴充/修改/刪減功能的集中地)
│   ├── __init__.py
│   ├── base.py                   # BaseTask 抽象基類 (定義 run, 參數模型與執行生命週期)
│   ├── registry.py               # TaskRegistry 註冊中心 (自動掃描、狀態開關與 Schema 自省)
│   └── builtin/                  # 內建任務實作範本
│       ├── __init__.py
│       ├── health_probe.py       # 系統健康探針任務 (執行 JS 運算檢測引擎健康度)
│       └── web_inspector.py      # 通用網頁巡檢任務 (導航、檢查狀態碼、標題、選擇性截圖)
│
├── api/                          # 🌐 HTTP REST API 服務介面
│   ├── __init__.py
│   ├── routes.py                 # FastAPI 路由定義 (/health, /api/v1/tasks)
│   └── schemas.py                # 請求與響應 Pydantic 資料結構定義
│
├── tests/                        # 🧪 自動化測試套件 (持續整合品質保證)
│   ├── __init__.py
│   ├── test_health.py            # 健康探針端點測試
│   ├── test_security.py          # API Key 鑑權防護測試
│   ├── test_task_registry.py     # 插件註冊、動態探索與開關測試
│   └── test_browser_lifecycle.py # 瀏覽器沙盒隔離與錯誤保護測試
│
├── logs/                         # 📝 系統運行日誌 (自動建立，每天輪轉與壓縮)
└── artifacts/                    # 📦 產出物保存目錄 (自動建立)
    ├── failures/                 # 任務異常時自動儲存之畫面快照
    └── screenshots/              # 業務任務指定保存之網頁截圖
```

---

## 🚀 快速開始指南 (使用 uv)

本專案完全以 `uv` 為現代套件管理標準，方便在任何機器與場景快速且一致地重現環境。

### 1. 安裝環境相依套件
在專案根目錄執行：
```powershell
uv sync
```

### 2. 安裝 Playwright 瀏覽器引擎 (Chromium)
```powershell
uv run playwright install chromium
```

### 3. 配置環境變數
複製範本並依需求修改（預設配置已可直接運行）：
```powershell
Copy-Item .env.example .env
```

### 4. 啟動常駐服務 (Daemon Mode)
```powershell
uv run python main.py
```
服務將啟動並監聽於 `http://127.0.0.1:8000`，內建 Swagger UI 可於瀏覽器開啟：`http://127.0.0.1:8000/docs`。

### 5. CLI 單次執行模式 (免開 API 服務直接除錯)
可在命令列直接執行任意任務並印出 JSON 結果：
```powershell
# 執行系統探針
uv run python main.py run-task system_health_probe

# 執行網頁巡檢任務帶參數
uv run python main.py run-task web_inspector '{\"url\": \"https://example.com\", \"take_screenshot\": true}'
```

### 6. 執行自動化測試
驗證系統功能、安全閘門與瀏覽器資源調度無誤：
```powershell
uv run pytest -v
```

---

## 🧩 如何新增 / 修改 / 刪減功能 (任務插件擴充指南)

未來的任何自動化功能變更，**僅需在 `tasks/builtin/` (或自訂目錄) 中建立單一檔案**，系統啟動時會透過 `auto_discover` 自動載入。

### 示範：新增一個自訂登入檢測任務

在 `tasks/builtin/` 目錄下新增 `my_custom_task.py`：

```python
from pydantic import BaseModel, Field
from playwright.async_api import Page, BrowserContext
from tasks.base import BaseTask, TaskMetadata

# 1. 定義此任務所需的輸入參數 (具備嚴格型別校驗)
class MyTaskParams(BaseModel):
    target_url: str = Field(..., description="目標檢驗網址")
    timeout_ms: int = Field(default=15000, description="最大逾時毫秒數")

# 2. 實作任務本體 (繼承 BaseTask)
class MyCustomTask(BaseTask):
    metadata = TaskMetadata(
        name="my_custom_task",              # 任務唯一識別碼
        description="自訂業務自動化工作範例",
        version="1.0.0",
        author="User",
        tags=["business", "custom"],
        enabled=True,                        # 可設為 False 停用
    )
    param_model = MyTaskParams

    async def run(self, page: Page, context: BrowserContext, params: MyTaskParams) -> dict:
        # page 已由底層分配獨立沙盒，不與其他任務共用
        await page.goto(params.target_url, timeout=params.timeout_ms)
        title = await page.title()
        
        # 執行您需要的 Playwright 自動化操作...
        
        return {
            "title": title,
            "status": "completed_successfully"
        }
```

* **如何刪除功能？** 直接將對應的 `.py` 檔案自 `tasks/builtin/` 移除即可。
* **如何暫時停用功能？** 
  - 方式 A：將類別中 `TaskMetadata` 的 `enabled=False`。
  - 方式 B：透過 API 直接發送狀態切換請求（免重啟服務）。

---

## 🔐 安全性與 API 調用範例

所有 `/api/v1/*` 介面均受到 `X-API-Key` 鑑權保護。預設金鑰定義於 `.env` 中的 `API_SECRET_KEY`。

### 1. 健康檢查探針 (免 Key 或帶 Key 均可快速查詢)
```bash
curl http://127.0.0.1:8000/health
```
**回應範例**：
```json
{
  "service": "playwright-service",
  "status": "healthy",
  "latency_ms": 32.15,
  "browser_connected": true,
  "available_permits": 5,
  "error": null
}
```

### 2. 查詢所有已註冊任務與參數規格 (JSON Schema)
```bash
curl -H "X-API-Key: change-me-to-a-secure-secret-key" \
     http://127.0.0.1:8000/api/v1/tasks
```

### 3. 觸發執行特定任務
```bash
curl -X POST \
     -H "Content-Type: application/json" \
     -H "X-API-Key: change-me-to-a-secure-secret-key" \
     -d '{"params": {"url": "https://example.com", "take_screenshot": true}}' \
     http://127.0.0.1:8000/api/v1/tasks/web_inspector/run
```

### 4. 動態啟用 / 停用特定任務
```bash
curl -X POST \
     -H "Content-Type: application/json" \
     -H "X-API-Key: change-me-to-a-secure-secret-key" \
     -d '{"enabled": false}' \
     http://127.0.0.1:8000/api/v1/tasks/web_inspector/status
```

---

## 🛡️ 常駐運維與故障排查

1. **日誌查閱**：所有日誌即時輸出於終端機，並寫入 `logs/app.log`。日誌支援每天與滿 10MB 自動輪轉壓縮，保留 14 天。
2. **失敗快照查閱**：當任何自動化腳本發生未處理例外時，系統會自動將崩潰時的畫面拍攝並存放在 `artifacts/failures/fail_<task_name>_<timestamp>.png`。
3. **記憶體控制**：可透過 `.env` 中的 `MAX_CONCURRENT_CONTEXTS` 控制最大同時執行的瀏覽器標籤頁數，預設為 5，避免主機記憶體耗盡。
