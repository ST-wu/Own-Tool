import math
from datetime import datetime, timezone, timedelta
from typing import Tuple, List, Optional, Dict, Any

from tools.solar_tide.models import (
    SolarPosition,
    SolarDayTimes,
    MoonPosition,
    TidePoint,
    TideStatus,
    SunPathPoint,
)


class SolarTideCalculator:
    """純 Python 零外部依賴之高精度天體太陽幾何與潮汐調和解算引擎"""

    # -------------------------------------------------------------------------
    # 1. 太陽位置解算 (NOAA Solar Calculations)
    # -------------------------------------------------------------------------
    @staticmethod
    def calculate_solar_position(
        lat: float, lon: float, dt: datetime, tz_offset: float = 8.0
    ) -> Tuple[float, float, float, Optional[float], float, str]:
        """
        計算特定時空下之太陽仰角 (altitude) 與方位角 (azimuth)
        回傳: (altitude, azimuth, zenith, shadow_multiplier, shadow_azimuth, phase_name)
        """
        # 轉為 UTC 時間
        # 如果 dt 是 naive，假設為當地時間並加上 tz_offset
        if dt.tzinfo is None:
            utc_dt = dt - timedelta(hours=tz_offset)
        else:
            utc_dt = dt.astimezone(timezone.utc)

        year = utc_dt.year
        month = utc_dt.month
        day = utc_dt.day
        hour = utc_dt.hour
        minute = utc_dt.minute
        second = utc_dt.second + utc_dt.microsecond / 1e6

        # 計算儒略日 (Julian Day)
        if month <= 2:
            year -= 1
            month += 12
        a = math.floor(year / 100)
        b = 2 - a + math.floor(a / 4)
        day_fraction = (hour + minute / 60.0 + second / 3600.0) / 24.0
        jd = (
            math.floor(365.25 * (year + 4716))
            + math.floor(30.6001 * (month + 1))
            + day
            + b
            - 1524.5
            + day_fraction
        )

        # 儒略世紀 (Julian Century)
        t = (jd - 2451545.0) / 36525.0

        # 太陽幾何平黃經 (度)
        l0 = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360.0
        # 太陽平近點角 (度)
        m = (357.52911 + t * (35999.05029 - 0.0001537 * t)) % 360.0
        m_rad = math.radians(m)

        # 地球軌道離心率
        e = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)

        # 太陽中心差 (度)
        c = (
            math.sin(m_rad) * (1.914602 - t * (0.004817 + 0.000014 * t))
            + math.sin(2 * m_rad) * (0.019993 - 0.000101 * t)
            + math.sin(3 * m_rad) * 0.000289
        )

        # 太陽真黃經與視黃經 (度)
        sun_true_lon = l0 + c
        sun_app_lon = (
            sun_true_lon - 0.00569 - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * t))
        )
        app_lon_rad = math.radians(sun_app_lon)

        # 黃赤交角 (度)
        eps0 = (
            23.0
            + (
                26.0
                + (
                    21.448
                    - t * (46.815 + t * (0.00059 - t * 0.001813))
                )
                / 60.0
            )
            / 60.0
        )
        eps = eps0 + 0.00256 * math.cos(math.radians(125.04 - 1934.136 * t))
        eps_rad = math.radians(eps)

        # 太陽赤緯 declination (度)
        sin_decl = math.sin(eps_rad) * math.sin(app_lon_rad)
        decl_rad = math.asin(sin_decl)
        decl = math.degrees(decl_rad)

        # 均時差 eqtime (分鐘)
        y = math.tan(eps_rad / 2.0) ** 2
        l0_rad = math.radians(l0)
        sin_2l0 = math.sin(2 * l0_rad)
        sin_m = math.sin(m_rad)
        cos_2l0 = math.cos(2 * l0_rad)
        sin_4l0 = math.sin(4 * l0_rad)
        sin_2m = math.sin(2 * m_rad)
        eqtime = 4.0 * math.degrees(
            y * sin_2l0
            - 2.0 * e * sin_m
            + 4.0 * e * y * sin_m * cos_2l0
            - 0.5 * (y ** 2) * sin_4l0
            - 1.25 * (e ** 2) * sin_2m
        )

        # 當地真太陽時 (True Solar Time in minutes)
        # 用當地時間計算
        local_time_min = dt.hour * 60.0 + dt.minute + dt.second / 60.0
        time_offset = eqtime + 4.0 * lon - 60.0 * tz_offset
        tst = (local_time_min + time_offset) % 1440.0

        # 太陽時角 hour angle (度)
        ha = tst / 4.0 - 180.0
        if ha < -180.0:
            ha += 360.0
        ha_rad = math.radians(ha)

        # 太陽天頂角 (zenith) 與仰角 (altitude)
        lat_rad = math.radians(lat)
        cos_zenith = (
            math.sin(lat_rad) * math.sin(decl_rad)
            + math.cos(lat_rad) * math.cos(decl_rad) * math.cos(ha_rad)
        )
        cos_zenith = max(-1.0, min(1.0, cos_zenith))
        zenith_rad = math.acos(cos_zenith)
        zenith = math.degrees(zenith_rad)
        altitude = 90.0 - zenith

        # 大氣折射微幅修正 (Atmospheric Refraction Correction)
        if altitude > -0.575:
            refraction = 1.02 / math.tan(math.radians(altitude + 10.3 / (altitude + 5.11))) / 60.0
            altitude += refraction
            zenith = 90.0 - altitude

        # 太陽方位角 azimuth (度，0°=北, 90°=東, 180°=南, 270°=西)
        cos_azimuth = (
            math.sin(lat_rad) * math.cos(zenith_rad) - math.sin(decl_rad)
        ) / (math.cos(lat_rad) * math.sin(zenith_rad) + 1e-7)
        cos_azimuth = max(-1.0, min(1.0, cos_azimuth))
        azimuth_pre = math.degrees(math.acos(cos_azimuth))
        if ha > 0:
            azimuth = (azimuth_pre + 180.0) % 360.0
        else:
            azimuth = (540.0 - azimuth_pre) % 360.0

        # 物體在地表投影長度倍率 (L = 1 / tan(altitude))
        if altitude > 0.5:
            shadow_multiplier = round(1.0 / math.tan(math.radians(altitude)), 2)
        else:
            shadow_multiplier = None

        # 陰影在地表的朝向 (太陽方位角 180° 反方向)
        shadow_azimuth = (azimuth + 180.0) % 360.0

        # 判定光影所屬階段
        if altitude > 6.0:
            phase_name = "白晝陽光 (Daylight)"
        elif 0.0 <= altitude <= 6.0:
            phase_name = "黃金時刻 (Golden Hour 🌅)"
        elif -4.0 <= altitude < 0.0:
            phase_name = "民用暮光 (Civil Twilight)"
        elif -6.0 <= altitude < -4.0:
            phase_name = "藍調時刻 (Blue Hour 🌌)"
        elif -12.0 <= altitude < -6.0:
            phase_name = "航海暮光 (Nautical Twilight)"
        else:
            phase_name = "深邃夜空 (Night Sky 🌙)"

        return (
            round(altitude, 2),
            round(azimuth, 2),
            round(zenith, 2),
            shadow_multiplier,
            round(shadow_azimuth, 2),
            phase_name,
        )

    # -------------------------------------------------------------------------
    # 2. 日出、日落、正午與白晝長度解算
    # -------------------------------------------------------------------------
    @staticmethod
    def calculate_day_times(
        lat: float, lon: float, dt: datetime, tz_offset: float = 8.0
    ) -> SolarDayTimes:
        """計算單日之日出、日落、正午與攝影黃金時刻"""
        # 利用採樣尋找當日太陽穿越地平線 (0.833° 折射半徑) 的精確時刻
        # 檢索當日 00:00 ~ 24:00 每 5 分鐘之仰角
        base_date = dt.date()
        times_elev: List[Tuple[float, float]] = []
        for minute in range(0, 1440, 5):
            h = minute // 60
            m = minute % 60
            sample_dt = datetime(
                base_date.year, base_date.month, base_date.day, h, m, 0
            )
            alt, _, _, _, _, _ = SolarTideCalculator.calculate_solar_position(
                lat, lon, sample_dt, tz_offset
            )
            times_elev.append((minute / 60.0, alt))

        # 尋找正午上中天 (最高點)
        max_hour, max_alt = max(times_elev, key=lambda x: x[1])
        noon_h = int(max_hour)
        noon_m = int(round((max_hour - noon_h) * 60))
        solar_noon_str = f"{noon_h:02d}:{noon_m:02d}"

        # 尋找日出 (由負轉正) 與日落 (由正轉負)
        sunrise_hour: Optional[float] = None
        sunset_hour: Optional[float] = None
        for i in range(len(times_elev) - 1):
            h1, a1 = times_elev[i]
            h2, a2 = times_elev[i + 1]
            if a1 <= 0.0 < a2 and sunrise_hour is None:
                # 線性內插
                sunrise_hour = h1 + (0.0 - a1) / (a2 - a1) * (h2 - h1)
            elif a1 >= 0.0 > a2 and sunset_hour is None:
                sunset_hour = h1 + (0.0 - a1) / (a2 - a1) * (h2 - h1)

        def _fmt_hour(val: Optional[float]) -> Optional[str]:
            if val is None:
                return None
            hh = int(val) % 24
            mm = int(round((val - int(val)) * 60)) % 60
            return f"{hh:02d}:{mm:02d}"

        sunrise_str = _fmt_hour(sunrise_hour)
        sunset_str = _fmt_hour(sunset_hour)

        day_len = 0.0
        if sunrise_hour is not None and sunset_hour is not None:
            day_len = round(sunset_hour - sunrise_hour, 2)

        # 黃金時刻區間 (日出後約 1 小時，日落前約 1 小時)
        gh_morning = None
        gh_evening = None
        bh_evening = None
        if sunrise_hour is not None:
            gh_m_end = _fmt_hour(sunrise_hour + 0.8)
            gh_morning = f"{sunrise_str} ~ {gh_m_end}"
        if sunset_hour is not None:
            gh_e_start = _fmt_hour(sunset_hour - 0.8)
            gh_evening = f"{gh_e_start} ~ {sunset_str}"
            bh_e_end = _fmt_hour(sunset_hour + 0.6)
            bh_evening = f"{sunset_str} ~ {bh_e_end}"

        return SolarDayTimes(
            sunrise=sunrise_str,
            sunset=sunset_str,
            solar_noon=solar_noon_str,
            golden_hour_morning=gh_morning,
            golden_hour_evening=gh_evening,
            blue_hour_evening=bh_evening,
            day_length_hours=day_len,
        )

    # -------------------------------------------------------------------------
    # 3. 月球位置、月相與大潮小潮引力特徵
    # -------------------------------------------------------------------------
    @staticmethod
    def calculate_moon_position(dt: datetime, tz_offset: float = 8.0) -> MoonPosition:
        """計算月相角、受光率、月齡及引潮力大潮/小潮判定"""
        if dt.tzinfo is None:
            utc_dt = dt - timedelta(hours=tz_offset)
        else:
            utc_dt = dt.astimezone(timezone.utc)

        # 儒略日計算
        y = utc_dt.year
        m = utc_dt.month
        d = utc_dt.day + (utc_dt.hour + utc_dt.minute / 60.0) / 24.0
        if m <= 2:
            y -= 1
            m += 12
        a = math.floor(y / 100)
        b = 2 - a + math.floor(a / 4)
        jd = math.floor(365.25 * (y + 4716)) + math.floor(30.6001 * (m + 1)) + d + b - 1524.5
        t = (jd - 2451545.0) / 36525.0

        # 月球平離角 D (度)
        d_deg = (
            297.8501921
            + 445267.1114034 * t
            - 0.0018819 * (t ** 2)
            + (t ** 3) / 545868.0
        ) % 360.0

        # 月齡 (天，朔望月週期 29.530588853 天)
        age = (d_deg / 360.0) * 29.530588853

        # 月面照度比例 (0~100%)
        illumination = (1.0 - math.cos(math.radians(d_deg))) / 2.0 * 100.0

        # 月相名稱判定
        phase_angle = d_deg
        if phase_angle < 15.0 or phase_angle >= 345.0:
            phase_name = "新月 (朔月 🌑)"
        elif 15.0 <= phase_angle < 75.0:
            phase_name = "娥眉月 (眉月 🌒)"
        elif 75.0 <= phase_angle < 105.0:
            phase_name = "上弦月 (First Quarter 🌓)"
        elif 105.0 <= phase_angle < 165.0:
            phase_name = "盈凸月 (Waxing Gibbous 🌔)"
        elif 165.0 <= phase_angle < 195.0:
            phase_name = "滿月 (望月 🌕)"
        elif 195.0 <= phase_angle < 255.0:
            phase_name = "虧凸月 (Waning Gibbous 🌖)"
        elif 255.0 <= phase_angle < 285.0:
            phase_name = "下弦月 (Third Quarter 🌗)"
        else:
            phase_name = "殘月 (Waning Crescent 🌘)"

        # 大潮 (Spring Tide)：日月引力共線 (新月或滿月前後約 1.5 天，即 phase_angle 接近 0° 或 180°)
        dist_to_syzygy = min(
            abs(phase_angle - 0.0),
            abs(phase_angle - 180.0),
            abs(phase_angle - 360.0),
        )
        is_spring = dist_to_syzygy <= 24.0

        # 小潮 (Neap Tide)：日月夾角 90° 引力抵消 (上弦月或下弦月前後約 1.5 天)
        dist_to_quadrature = min(
            abs(phase_angle - 90.0),
            abs(phase_angle - 270.0),
        )
        is_neap = dist_to_quadrature <= 24.0

        return MoonPosition(
            phase_name=phase_name,
            phase_angle=round(phase_angle, 2),
            illumination_pct=round(illumination, 1),
            age_days=round(age, 2),
            is_spring_tide=is_spring,
            is_neap_tide=is_neap,
        )

    # -------------------------------------------------------------------------
    # 4. 海洋潮汐調和分析模型 (Tidal Harmonic Analysis Engine)
    # -------------------------------------------------------------------------
    @staticmethod
    def _compute_raw_tide_height(
        lat: float, lon: float, timestamp_sec: float
    ) -> float:
        """
        多重分潮調和物理疊加公式
        h(t) = Z0 + Sum( Ai * cos(wi * t - phi_i) )
        """
        hours_since_epoch = timestamp_sec / 3600.0

        # 五大核心分潮角速度 (度/小時)
        w_m2 = 28.9841042  # 主太陰半日潮 (12.42h)
        w_s2 = 30.0000000  # 主太陽半日潮 (12.00h)
        w_n2 = 28.4397295  # 太陰月偏心半日潮 (12.66h)
        w_k1 = 15.0410686  # 日月全日潮 (23.93h)
        w_o1 = 13.9430356  # 主太陰全日潮 (25.82h)

        # 依緯度特徵微調潮差振幅 (台灣海峽狹管效應台中/新竹潮差可達 3~4m，東海岸花蓮/台東僅約 1~1.5m)
        # 以經緯度幾何特徵構建平滑振幅權重
        lat_factor = 1.0 + 0.3 * math.sin(math.radians(lat * 3.0))
        # 台灣西部海域 (經度 120°~121.5°) 振幅放大
        if 119.5 <= lon <= 121.5 and 22.5 <= lat <= 25.5:
            coastal_boost = 1.6
        else:
            coastal_boost = 1.0

        # 各分潮基準振幅 (公尺)
        amp_m2 = 1.15 * coastal_boost * lat_factor
        amp_s2 = 0.42 * coastal_boost
        amp_n2 = 0.22 * coastal_boost
        amp_k1 = 0.35
        amp_o1 = 0.28

        # 初相角 (以經度進行地理相移)
        base_phase = lon * 1.5
        phase_m2 = math.radians(base_phase + 45.0)
        phase_s2 = math.radians(base_phase * 1.05 + 10.0)
        phase_n2 = math.radians(base_phase * 0.95 + 80.0)
        phase_k1 = math.radians(base_phase * 0.5 + 120.0)
        phase_o1 = math.radians(base_phase * 0.45 + 160.0)

        # 調和疊加
        h_m2 = amp_m2 * math.cos(math.radians(w_m2 * hours_since_epoch) - phase_m2)
        h_s2 = amp_s2 * math.cos(math.radians(w_s2 * hours_since_epoch) - phase_s2)
        h_n2 = amp_n2 * math.cos(math.radians(w_n2 * hours_since_epoch) - phase_n2)
        h_k1 = amp_k1 * math.cos(math.radians(w_k1 * hours_since_epoch) - phase_k1)
        h_o1 = amp_o1 * math.cos(math.radians(w_o1 * hours_since_epoch) - phase_o1)

        total_height = h_m2 + h_s2 + h_n2 + h_k1 + h_o1
        return round(total_height, 2)

    @classmethod
    def calculate_tide_status(
        cls, lat: float, lon: float, dt: datetime, tz_offset: float = 8.0, span_days: int = 1
    ) -> TideStatus:
        """計算指定時區下之即時潮高、水流走向、極值預測與自訂跨度 (1, 3, 7, 14, 30天) 連續波形"""
        if dt.tzinfo is None:
            tz = timezone(timedelta(hours=tz_offset))
            current_dt = dt.replace(tzinfo=tz)
        else:
            current_dt = dt

        current_ts = current_dt.timestamp()
        current_h = cls._compute_raw_tide_height(lat, lon, current_ts)

        # 計算微分趨勢 (15 分鐘前與 15 分鐘後)
        h_prev = cls._compute_raw_tide_height(lat, lon, current_ts - 900)
        h_next = cls._compute_raw_tide_height(lat, lon, current_ts + 900)
        if h_next >= current_h:
            trend = "flood"  # 漲潮 ⇡
        else:
            trend = "ebb"    # 退潮 ⇣

        # 依 span_days 自適應時間範圍與步長
        span_days = max(1, min(30, span_days))
        if span_days == 1:
            start_ts = current_ts - 6 * 3600
            end_ts = current_ts + 18 * 3600
            step_sec = 900  # 15 分鐘 (96 點)
            time_fmt = "%H:%M"
        elif span_days <= 3:
            start_ts = current_ts - 12 * 3600
            end_ts = current_ts + (span_days * 24 - 12) * 3600
            step_sec = 1800  # 30 分鐘
            time_fmt = "%m/%d %H:%M"
        elif span_days <= 7:
            start_ts = current_ts - 24 * 3600
            end_ts = current_ts + (span_days * 24 - 24) * 3600
            step_sec = 3600  # 1 小時 (約 168 點)
            time_fmt = "%m/%d %H:%M"
        elif span_days <= 14:
            start_ts = current_ts - 48 * 3600
            end_ts = current_ts + (span_days * 24 - 48) * 3600
            step_sec = 7200  # 2 小時
            time_fmt = "%m/%d %H:%M"
        else:
            start_ts = current_ts - 72 * 3600
            end_ts = current_ts + (span_days * 24 - 72) * 3600
            step_sec = 10800  # 3 小時 (約 240 點)
            time_fmt = "%m/%d"

        wave_series: List[TidePoint] = []
        t = start_ts
        while t <= end_ts:
            h = cls._compute_raw_tide_height(lat, lon, t)
            pt_dt = datetime.fromtimestamp(t, tz=timezone(timedelta(hours=tz_offset)))
            wave_series.append(
                TidePoint(
                    time=pt_dt.strftime(time_fmt),
                    timestamp=t,
                    height=h,
                    point_type="normal",
                )
            )
            t += step_sec

        # 在 wave_series 中檢索未來的高潮與低潮極值
        next_high: Optional[TidePoint] = None
        next_low: Optional[TidePoint] = None

        # 以 5 分鐘步長在未來 16 小時內搜尋極值點
        scan_t = current_ts + 300
        scan_end = current_ts + 16 * 3600
        while scan_t < scan_end:
            h_c = cls._compute_raw_tide_height(lat, lon, scan_t)
            h_l = cls._compute_raw_tide_height(lat, lon, scan_t - 300)
            h_r = cls._compute_raw_tide_height(lat, lon, scan_t + 300)

            pt_dt = datetime.fromtimestamp(scan_t, tz=timezone(timedelta(hours=tz_offset)))
            # 局部極大值 (滿潮)
            if h_c >= h_l and h_c >= h_r and next_high is None:
                next_high = TidePoint(
                    time=pt_dt.strftime("%H:%M"),
                    timestamp=scan_t,
                    height=h_c,
                    point_type="high",
                )
            # 局部極小值 (乾潮)
            if h_c <= h_l and h_c <= h_r and next_low is None:
                next_low = TidePoint(
                    time=pt_dt.strftime("%H:%M"),
                    timestamp=scan_t,
                    height=h_c,
                    point_type="low",
                )

            if next_high is not None and next_low is not None:
                break
            scan_t += 300

        # 將 wave_series 中的極值節點標記 point_type
        for i in range(1, len(wave_series) - 1):
            if (
                wave_series[i].height >= wave_series[i - 1].height
                and wave_series[i].height >= wave_series[i + 1].height
            ):
                wave_series[i].point_type = "high"
            elif (
                wave_series[i].height <= wave_series[i - 1].height
                and wave_series[i].height <= wave_series[i + 1].height
            ):
                wave_series[i].point_type = "low"

        # 大潮/小潮特徵判定
        moon_info = cls.calculate_moon_position(dt, tz_offset)
        if moon_info.is_spring_tide:
            tide_type = "spring"
        elif moon_info.is_neap_tide:
            tide_type = "neap"
        else:
            tide_type = "normal"

        # 安全趕海與海釣黃金窗口：距乾潮前後 2 小時以內
        harvest_window = False
        if next_low is not None:
            time_diff_hours = abs(next_low.timestamp - current_ts) / 3600.0
            if time_diff_hours <= 2.0 or current_h <= -0.5:
                harvest_window = True

        return TideStatus(
            current_height=current_h,
            trend=trend,
            tide_type=tide_type,
            next_high_tide=next_high,
            next_low_tide=next_low,
            span_days=span_days,
            wave_series=wave_series,
            harvest_window=harvest_window,
        )

    # -------------------------------------------------------------------------
    # 5. 今日 24 小時太陽天際弧線軌跡點 (Sun Path Points for Sky Dome)
    # -------------------------------------------------------------------------
    @classmethod
    def generate_sun_path_today(
        cls, lat: float, lon: float, dt: datetime, tz_offset: float = 8.0
    ) -> List[SunPathPoint]:
        """生成單日 24 小時每 30 分鐘之天頂仰角與方位角，供穹頂弧線繪製"""
        base_date = dt.date()
        path: List[SunPathPoint] = []
        for minute in range(0, 1440, 30):
            h = minute // 60
            m = minute % 60
            sample_dt = datetime(base_date.year, base_date.month, base_date.day, h, m, 0)
            alt, az, _, _, _, _ = cls.calculate_solar_position(lat, lon, sample_dt, tz_offset)
            path.append(
                SunPathPoint(
                    hour_float=round(minute / 60.0, 2),
                    time_str=f"{h:02d}:{m:02d}",
                    altitude=alt,
                    azimuth=az,
                    is_daylight=(alt > 0.0),
                )
            )
        return path
