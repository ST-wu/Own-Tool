from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class LocationInfo(BaseModel):
    """地理位置資訊"""
    id: Optional[str] = None
    name: str = Field(..., description="地點名稱 (如 淡水漁人碼頭 或 電腦目前位置)")
    latitude: float = Field(..., ge=-90.0, le=90.0, description="緯度")
    longitude: float = Field(..., ge=-180.0, le=180.0, description="經度")
    timezone_offset: float = Field(default=8.0, description="時區偏移 (小時，台灣為 +8.0)")
    is_current_device: bool = Field(default=False, description="是否為本機裝置定位")


class SolarPosition(BaseModel):
    """即時太陽幾何座標與光影"""
    altitude: float = Field(..., description="仰角 (度，-90°~90°，0° 為地平線)")
    azimuth: float = Field(..., description="方位角 (度，0°~360°，0°=北, 90°=東, 180°=南, 270°=西)")
    zenith: float = Field(..., description="天頂角 (90° - altitude)")
    is_daylight: bool = Field(..., description="是否為白晝")
    shadow_multiplier: Optional[float] = Field(None, description="物體投影長度倍率 (1/tan(alt))")
    shadow_azimuth: float = Field(..., description="地表陰影朝向方位角 (度)")
    phase_name: str = Field(..., description="光影階段名稱 (白晝/黃金時刻/藍調時刻/民用暮光/深邃黑夜)")


class SolarDayTimes(BaseModel):
    """單日重要太陽節點時刻"""
    sunrise: Optional[str] = Field(None, description="日出時間 (HH:MM)")
    sunset: Optional[str] = Field(None, description="日落時間 (HH:MM)")
    solar_noon: Optional[str] = Field(None, description="正午上中天時間 (HH:MM)")
    golden_hour_morning: Optional[str] = Field(None, description="晨曦黃金時刻 (HH:MM~HH:MM)")
    golden_hour_evening: Optional[str] = Field(None, description="夕陽黃金時刻 (HH:MM~HH:MM)")
    blue_hour_evening: Optional[str] = Field(None, description="暮光藍調時刻 (HH:MM~HH:MM)")
    day_length_hours: float = Field(..., description="白晝總時長 (小時)")


class MoonPosition(BaseModel):
    """月球位置與月相引潮力特徵"""
    phase_name: str = Field(..., description="月相名稱 (新月/上弦月/滿月/下弦月等)")
    phase_angle: float = Field(..., description="月相角 (度，0°~360°)")
    illumination_pct: float = Field(..., description="月面受光率百分比 (0~100%)")
    age_days: float = Field(..., description="月齡 (天，0~29.53)")
    is_spring_tide: bool = Field(..., description="是否為大潮 (朔望月前後日月引力疊加)")
    is_neap_tide: bool = Field(..., description="是否為小潮 (上下弦月前後日月引力抵消)")


class TidePoint(BaseModel):
    """潮汐離散走勢節點"""
    time: str = Field(..., description="時間字串 (HH:MM 或 ISO)")
    timestamp: float = Field(..., description="Unix 時間戳")
    height: float = Field(..., description="潮位高度 (公尺)")
    point_type: str = Field(default="normal", description="節點類型 (high滿潮/low乾潮/normal走勢)")


class TideStatus(BaseModel):
    """即時潮汐狀態與預報走勢"""
    current_height: float = Field(..., description="當前即時潮高 (公尺)")
    trend: str = Field(..., description="潮汐水流走向 (flood 漲潮 ⇡ / ebb 退潮 ⇣)")
    tide_type: str = Field(..., description="潮汐特徵 (spring 大潮 / neap 小潮 / normal 中潮)")
    next_high_tide: Optional[TidePoint] = Field(None, description="下次滿潮時間與極值")
    next_low_tide: Optional[TidePoint] = Field(None, description="下次乾潮時間與極值")
    span_days: int = Field(default=1, description="潮汐波形時間跨度天數")
    wave_series: List[TidePoint] = Field(default_factory=list, description="平滑潮位波動點集")
    harvest_window: bool = Field(..., description="是否處於乾潮前後 2 小時黃金趕海/採集/海釣窗口")


class SunPathPoint(BaseModel):
    """天際太陽軌跡點"""
    hour_float: float
    time_str: str
    altitude: float
    azimuth: float
    is_daylight: bool


class SolarTideCalculationRequest(BaseModel):
    """日潮星象儀查詢請求"""
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    location_name: Optional[str] = "自訂位置"
    timezone_offset: Optional[float] = 8.0
    datetime_iso: Optional[str] = Field(None, description="目標時間 (ISO 格式，留空則採用伺服器/電腦即時時間)")
    span_days: Optional[int] = Field(default=1, ge=1, le=30, description="潮汐波形展示時間跨度天數 (1, 3, 7, 14, 30)")


class WeatherInfo(BaseModel):
    """即時大氣與微氣候資訊"""
    temperature: float = Field(..., description="氣溫 (°C)")
    apparent_temperature: float = Field(..., description="體感溫度 (°C)")
    humidity: float = Field(..., description="相對濕度 (%)")
    condition: str = Field(..., description="天氣代碼 (clear/partly_cloudy/overcast/fog/drizzle/rain/heavy_rain/snow/thunderstorm)")
    condition_desc: str = Field(..., description="天氣文字敘述")
    detail_type: str = Field(..., description="細部天氣粒子與光影等級")
    precipitation: float = Field(default=0.0, description="降水量 (mm)")
    wind_speed_kmh: float = Field(default=0.0, description="風速 (km/h)")
    wind_direction_deg: float = Field(default=0.0, description="風向 (度，0° 為北風)")
    surface_pressure_hpa: float = Field(default=1013.25, description="地面氣壓 (hPa)")
    uv_index: float = Field(default=0.0, description="紫外線指數")
    is_cached: bool = Field(default=False, description="是否為快取或備援數據")


class SolarTideCalculationResponse(BaseModel):
    """日潮星象儀完整綜合回傳"""
    location: LocationInfo
    query_time_iso: str
    is_live_now: bool
    solar: SolarPosition
    day_times: SolarDayTimes
    moon: MoonPosition
    tide: TideStatus
    sun_path: List[SunPathPoint]
    weather: Optional[WeatherInfo] = None

