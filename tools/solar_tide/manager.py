from datetime import datetime, timezone, timedelta
from typing import List, Optional

from tools.solar_tide.models import (
    LocationInfo,
    SolarTideCalculationRequest,
    SolarTideCalculationResponse,
    SolarPosition,
)
from tools.solar_tide.calculator import SolarTideCalculator
from tools.solar_tide.weather import WeatherService



class SolarTideManager:
    """日潮星象儀管理核心：管理預設港口景點，協調太陽與潮汐計算"""

    DEFAULT_LOCATIONS: List[LocationInfo] = [
        LocationInfo(
            id="current_device",
            name="📍 電腦目前所在位置 (自動定位)",
            latitude=25.0330,
            longitude=121.5654,
            timezone_offset=8.0,
            is_current_device=True,
        ),
        LocationInfo(
            id="tamsui",
            name="淡水漁人碼頭 (新北)",
            latitude=25.1824,
            longitude=121.4116,
            timezone_offset=8.0,
        ),
        LocationInfo(
            id="keelung",
            name="基隆港 / 正濱漁港 (基隆)",
            latitude=25.1325,
            longitude=121.7451,
            timezone_offset=8.0,
        ),
        LocationInfo(
            id="taichung",
            name="台中港 / 高美濕地 (台中)",
            latitude=24.3122,
            longitude=120.5501,
            timezone_offset=8.0,
        ),
        LocationInfo(
            id="kaohsiung",
            name="高雄港 / 旗津海岸 (高雄)",
            latitude=22.6148,
            longitude=120.2736,
            timezone_offset=8.0,
        ),
        LocationInfo(
            id="kenting",
            name="墾丁白沙灣 / 鵝鑾鼻 (屏東)",
            latitude=21.9022,
            longitude=120.8526,
            timezone_offset=8.0,
        ),
        LocationInfo(
            id="penghu",
            name="澎湖馬公港 / 奎壁山摩西分海 (澎湖)",
            latitude=23.5888,
            longitude=119.6734,
            timezone_offset=8.0,
        ),
        LocationInfo(
            id="hualien",
            name="花蓮港 / 七星潭 (花蓮)",
            latitude=24.0315,
            longitude=121.6338,
            timezone_offset=8.0,
        ),
        LocationInfo(
            id="tokyo_bay",
            name="東京灣 (日本 / Tokyo Bay)",
            latitude=35.5300,
            longitude=139.8000,
            timezone_offset=9.0,
        ),
        LocationInfo(
            id="sf_bay",
            name="舊金山灣 (美國 / SF Bay)",
            latitude=37.8000,
            longitude=-122.4200,
            timezone_offset=-7.0,
        ),
    ]

    def get_locations(self) -> List[LocationInfo]:
        """取得預設港口與景點清單"""
        return self.DEFAULT_LOCATIONS

    def calculate(self, req: SolarTideCalculationRequest) -> SolarTideCalculationResponse:
        """綜合解算太陽、月球與潮汐狀態"""
        tz_offset = req.timezone_offset if req.timezone_offset is not None else 8.0
        tz = timezone(timedelta(hours=tz_offset))

        # 判定目標時間
        is_live_now = False
        if req.datetime_iso:
            try:
                # 支援帶時區或無時區 ISO 字串
                clean_iso = req.datetime_iso.replace("Z", "+00:00")
                parsed_dt = datetime.fromisoformat(clean_iso)
                if parsed_dt.tzinfo is None:
                    target_dt = parsed_dt.replace(tzinfo=tz)
                else:
                    target_dt = parsed_dt.astimezone(tz)
            except Exception:
                target_dt = datetime.now(tz=tz)
                is_live_now = True
        else:
            target_dt = datetime.now(tz=tz)
            is_live_now = True

        lat = req.latitude
        lon = req.longitude

        # 1. 太陽幾何解算
        alt, az, zen, shadow_mult, shadow_az, phase_name = (
            SolarTideCalculator.calculate_solar_position(
                lat=lat, lon=lon, dt=target_dt, tz_offset=tz_offset
            )
        )
        solar = SolarPosition(
            altitude=alt,
            azimuth=az,
            zenith=zen,
            is_daylight=(alt > 0.0),
            shadow_multiplier=shadow_mult,
            shadow_azimuth=shadow_az,
            phase_name=phase_name,
        )

        # 2. 單日重要太陽節點時刻
        day_times = SolarTideCalculator.calculate_day_times(
            lat=lat, lon=lon, dt=target_dt, tz_offset=tz_offset
        )

        # 3. 月球位置與月相特徵
        moon = SolarTideCalculator.calculate_moon_position(
            dt=target_dt, tz_offset=tz_offset
        )

        # 4. 海洋潮汐調和模型
        span_days = req.span_days if req.span_days is not None else 1
        tide = SolarTideCalculator.calculate_tide_status(
            lat=lat, lon=lon, dt=target_dt, tz_offset=tz_offset, span_days=span_days
        )

        # 5. 單日天頂太陽軌跡點集 (供穹頂圖繪製拱形金色軌道)
        sun_path = SolarTideCalculator.generate_sun_path_today(
            lat=lat, lon=lon, dt=target_dt, tz_offset=tz_offset
        )

        location_info = LocationInfo(
            name=req.location_name or f"自訂位置 ({lat:.2f}°, {lon:.2f}°)",
            latitude=lat,
            longitude=lon,
            timezone_offset=tz_offset,
        )

        # 6. 即時微氣候大氣資料
        weather = WeatherService.get_weather(lat=lat, lon=lon)

        return SolarTideCalculationResponse(
            location=location_info,
            query_time_iso=target_dt.isoformat(),
            is_live_now=is_live_now,
            solar=solar,
            day_times=day_times,
            moon=moon,
            tide=tide,
            sun_path=sun_path,
            weather=weather,
        )



solar_tide_manager = SolarTideManager()
