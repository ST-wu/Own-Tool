from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader
from config import settings
from core.logger import logger

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> str:
    """
    驗證請求標頭中的 API Key (Guard Clause 優先)
    未提供或不吻合時立即終止請求並紀錄安全審計日誌
    """
    # 提早退出：缺少金鑰
    if not api_key:
        logger.warning("[SECURITY_ALERT] 請求缺少 X-API-Key 鑑權標頭")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication key (X-API-Key header required)",
        )

    # 提早退出：金鑰不相符
    if api_key != settings.API_SECRET_KEY:
        logger.warning("[SECURITY_ALERT] 非法 API Key 嘗試訪問")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication key",
        )

    return api_key
