from pathlib import Path
from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse
from core.op_logger import op_logger
from tools.chaos_pendulum.presets import THEMES, PRESETS

pendulum_router = APIRouter(tags=["Chaos Pendulum"])
WEB_DIR = Path("web")


@pendulum_router.get("/pendulum", include_in_schema=False)
async def serve_pendulum_page():
    """提供混沌多連擺動態軌跡視覺系統頁面"""
    page_file = WEB_DIR / "pendulum.html"
    # Guard clause: 檢查頁面檔案是否存在
    if not page_file.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chaos Pendulum interface not found. Please verify web/ directory.",
        )

    op_logger.log(
        action="TOOL:PENDULUM_VIEW",
        status="INFO",
        details="使用者開啟混沌多連擺動態視覺頁面",
    )
    return FileResponse(page_file)


@pendulum_router.get("/api/v1/pendulum/themes")
async def get_pendulum_themes():
    """獲取可用之光譜主題清單"""
    return list(THEMES.values())


@pendulum_router.get("/api/v1/pendulum/presets")
async def get_pendulum_presets():
    """獲取內建預設運動參數配置"""
    return PRESETS
