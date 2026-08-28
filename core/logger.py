import sys
from loguru import logger
from config import settings


def setup_logger() -> None:
    """初始化結構化日誌記錄器，支援控制台與輪轉檔案輸出"""
    # 確保日誌與產出目錄存在
    settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
    settings.ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    # 清除預設配置
    logger.remove()

    # 控制台彩色輸出
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        colorize=True,
    )

    # 檔案日誌 (每天輪轉，最多保留 14 天，壓縮存檔)
    log_file = settings.LOG_DIR / "app.log"
    logger.add(
        str(log_file),
        level=settings.LOG_LEVEL,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="10 MB",
        retention="14 days",
        compression="zip",
        encoding="utf-8",
    )


# 模組加載時自動完成初始化
setup_logger()

__all__ = ["logger"]
