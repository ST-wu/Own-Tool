from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """應用程式全域配置設定中心"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # 服務監聽
    HOST: str = "127.0.0.1"
    PORT: int = 8000

    # 安全防護金鑰
    API_SECRET_KEY: str = "change-me-to-a-secure-secret-key"

    # Playwright 瀏覽器配置
    HEADLESS: bool = True
    BROWSER_TYPE: str = "chromium"
    MAX_CONCURRENT_CONTEXTS: int = 5
    CONTEXT_TIMEOUT_MS: int = 30000

    # 系統日誌與檔案儲存路徑
    LOG_LEVEL: str = "INFO"
    LOG_DIR: Path = Path("logs")
    ARTIFACTS_DIR: Path = Path("artifacts")

    # 背景排程設定 (秒數，0 表示停用)
    SCHEDULE_HEALTH_PROBE_SECONDS: int = 60


# 全域單例
settings = Settings()
