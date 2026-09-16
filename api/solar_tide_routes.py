import sys
from fastapi import APIRouter, HTTPException, Query
from typing import List, Optional

from core.logger import logger
from tools.solar_tide.models import (
    LocationInfo,
    SolarTideCalculationRequest,
    SolarTideCalculationResponse,
)
from tools.solar_tide.manager import solar_tide_manager

solar_tide_router = APIRouter(prefix="/api/solartide", tags=["Solar & Tide Observatory"])


@solar_tide_router.get("/locations", response_model=List[LocationInfo])
async def get_locations():
    """取得預設沿海港口與景點清單"""
    try:
        return solar_tide_manager.get_locations()
    except Exception as e:
        logger.error(f"[ERROR_SUMMARY] 取得地點清單失敗: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"無法取得地點清單: {str(e)}")


@solar_tide_router.post("/calculate", response_model=SolarTideCalculationResponse)
async def calculate_solar_tide(req: SolarTideCalculationRequest):
    """
    計算指定地點與時間之太陽幾何座標、日照時刻、月相引潮力與海域潮汐走勢
    若 datetime_iso 為空，自動採用電腦/伺服器即時時間 (Live Mode)
    """
    try:
        return solar_tide_manager.calculate(req)
    except Exception as e:
        logger.error(f"[ERROR_SUMMARY] 日潮星象計算失敗: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"日潮星象計算失敗: {str(e)}")


@solar_tide_router.get("/calculate_quick", response_model=SolarTideCalculationResponse)
async def calculate_quick(
    lat: float = Query(..., ge=-90.0, le=90.0, description="緯度"),
    lon: float = Query(..., ge=-180.0, le=180.0, description="經度"),
    name: Optional[str] = Query("自訂位置", description="地點名稱"),
    tz_offset: Optional[float] = Query(8.0, description="時區偏移小時數"),
    time_iso: Optional[str] = Query(None, description="ISO 時間字串 (留空代表即時)"),
    span_days: Optional[int] = Query(1, ge=1, le=30, description="潮汐波形跨度天數 (1, 3, 7, 14, 30)"),
):
    """GET 簡易快速查詢介面"""
    try:
        req = SolarTideCalculationRequest(
            latitude=lat,
            longitude=lon,
            location_name=name,
            timezone_offset=tz_offset,
            datetime_iso=time_iso,
            span_days=span_days,
        )
        return solar_tide_manager.calculate(req)
    except Exception as e:
        logger.error(f"[ERROR_SUMMARY] 快速日潮計算失敗: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"快速計算失敗: {str(e)}")
