import time
from typing import Dict, Any, Optional
import httpx

from core.logger import logger
from tools.solar_tide.models import WeatherInfo


class WeatherService:
    """微氣候資訊解算與 Open-Meteo API 快取服務"""

    # 10 分鐘記憶體快取: key -> (timestamp, WeatherInfo)
    _cache: Dict[str, tuple[float, WeatherInfo]] = {}
    CACHE_TTL_SECONDS = 600.0

    @classmethod
    def _get_cache_key(cls, lat: float, lon: float) -> str:
        return f"{lat:.2f}_{lon:.2f}"

    @classmethod
    def get_weather(cls, lat: float, lon: float) -> WeatherInfo:
        """獲取指定經緯度之即時微氣候數據 (優先讀取記憶體快取)"""
        cache_key = cls._get_cache_key(lat, lon)
        now = time.time()

        if cache_key in cls._cache:
            cached_time, cached_weather = cls._cache[cache_key]
            if now - cached_time < cls.CACHE_TTL_SECONDS:
                return cached_weather

        # 嘗試從 Open-Meteo API 抓取
        weather = cls._fetch_from_api(lat, lon)
        if weather is not None:
            cls._cache[cache_key] = (now, weather)
            return weather

        # 若 API 失敗，使用平滑合成降級數據
        fallback_weather = cls._generate_fallback_weather(lat, lon)
        return fallback_weather

    @classmethod
    def _fetch_from_api(cls, lat: float, lon: float) -> Optional[WeatherInfo]:
        """從 Open-Meteo 獲取真實氣候資料"""
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat:.4f}&longitude={lon:.4f}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,"
            f"precipitation,weather_code,wind_speed_10m,wind_direction_10m,"
            f"surface_pressure,uv_index"
            f"&timezone=auto"
        )
        try:
            with httpx.Client(timeout=3.5) as client:
                resp = client.get(url)
                if resp.status_code != 200:
                    logger.warning(f"[ERROR_SUMMARY] Open-Meteo 回應非 200: {resp.status_code}")
                    return None
                data = resp.json()
                current = data.get("current", {})

                w_code = int(current.get("weather_code", 0))
                temp = float(current.get("temperature_2m", 25.0))
                apparent_temp = float(current.get("apparent_temperature", temp))
                humidity = float(current.get("relative_humidity_2m", 65.0))
                precip = float(current.get("precipitation", 0.0))
                wind_speed = float(current.get("wind_speed_10m", 3.0))
                wind_dir = float(current.get("wind_direction_10m", 180.0))
                pressure = float(current.get("surface_pressure", 1013.0))
                uv = float(current.get("uv_index", 3.0))

                condition, desc, detail_type = cls._parse_wmo_code(w_code, precip)

                return WeatherInfo(
                    temperature=temp,
                    apparent_temperature=apparent_temp,
                    humidity=humidity,
                    condition=condition,
                    condition_desc=desc,
                    detail_type=detail_type,
                    precipitation=precip,
                    wind_speed_kmh=wind_speed,
                    wind_direction_deg=wind_dir,
                    surface_pressure_hpa=pressure,
                    uv_index=uv,
                    is_cached=False,
                )
        except Exception as e:
            logger.warning(f"[ERROR_SUMMARY] 天氣 API 請求異常: {type(e).__name__}: {e}")
            return None

    @classmethod
    def _parse_wmo_code(cls, code: int, precip: float) -> tuple[str, str, str]:
        """
        將 WMO 天氣代碼解析為：(condition, condition_desc, detail_type)
        detail_type 對應前端粒子與光影渲染等級
        """
        if code == 0:
            return "clear", "晴空萬里", "clear_sun"
        if code == 1:
            return "mostly_clear", "晴間少雲", "few_clouds"
        if code == 2:
            return "partly_cloudy", "多雲天色", "scattered_clouds"
        if code == 3:
            return "overcast", "陰天鉛灰", "overcast_thick"
        if code in (45, 48):
            return "fog", "大氣起霧", "dense_fog" if code == 48 else "light_fog"
        if code in (51, 53, 55):
            return "drizzle", "毛毛細雨", "light_drizzle"
        if code in (61, 63):
            return "rain", "中度降雨", "moderate_rain"
        if code == 65:
            return "heavy_rain", "傾盆大暴雨", "heavy_downpour"
        if code in (71, 73):
            return "snow", "輕舞飛雪", "gentle_snow"
        if code == 75:
            return "heavy_snow", "狂烈暴風雪", "blizzard"
        if code in (80, 81, 82):
            return "shower", "驟雨陣雨", "passing_shower"
        if code in (95, 96, 99):
            return "thunderstorm", "雷陣雨伴隨閃電", "thunder_lightning"

        if precip > 5.0:
            return "heavy_rain", "強烈降雨", "heavy_downpour"
        if precip > 0.5:
            return "rain", "陣雨綿綿", "moderate_rain"
        return "partly_cloudy", "舒適多雲", "scattered_clouds"

    @classmethod
    def _generate_fallback_weather(cls, lat: float, lon: float) -> WeatherInfo:
        """在離線或無外網時，依地理緯度提供合理的平滑氣候數值"""
        # 簡易緯度溫度模型
        base_temp = 28.0 - (abs(lat) * 0.3)
        return WeatherInfo(
            temperature=round(base_temp, 1),
            apparent_temperature=round(base_temp + 1.2, 1),
            humidity=72.0,
            condition="partly_cloudy",
            condition_desc="多雲舒適 (離線估算)",
            detail_type="scattered_clouds",
            precipitation=0.0,
            wind_speed_kmh=12.5,
            wind_direction_deg=75.0,
            surface_pressure_hpa=1012.0,
            uv_index=4.2,
            is_cached=True,
        )
