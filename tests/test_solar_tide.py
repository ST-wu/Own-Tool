import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from main import app
from tools.solar_tide.calculator import SolarTideCalculator
from tools.solar_tide.manager import solar_tide_manager
from tools.solar_tide.models import SolarTideCalculationRequest


@pytest.fixture
def client():
    return TestClient(app)


def test_solar_position_bounds():
    """測試太陽位置計算之物理數值邊界"""
    # 測試台北座標 (25.0330°N, 121.5654°E) 在 2026-06-21 夏至正午
    noon_dt = datetime(2026, 6, 21, 12, 0, 0)
    alt, az, zen, shadow_mult, shadow_az, phase = (
        SolarTideCalculator.calculate_solar_position(
            lat=25.0330, lon=121.5654, dt=noon_dt, tz_offset=8.0
        )
    )

    assert -90.0 <= alt <= 90.0
    assert 0.0 <= az <= 360.0
    assert 0.0 <= zen <= 180.0
    assert 0.0 <= shadow_az <= 360.0
    assert alt > 60.0  # 台北夏至正午太陽仰角應非常高 (> 60°)
    assert shadow_mult is not None
    assert shadow_mult < 1.0  # 影子很短


def test_solar_night_position():
    """測試深夜太陽仰角應為負值，且陰影倍率為 None"""
    night_dt = datetime(2026, 6, 21, 0, 30, 0)
    alt, az, zen, shadow_mult, shadow_az, phase = (
        SolarTideCalculator.calculate_solar_position(
            lat=25.0330, lon=121.5654, dt=night_dt, tz_offset=8.0
        )
    )
    assert alt < 0.0
    assert shadow_mult is None
    assert "夜" in phase or "暮光" in phase


def test_day_times_calculation():
    """測試日出日落與正午計算"""
    dt = datetime(2026, 9, 8, 10, 0, 0)
    day_times = SolarTideCalculator.calculate_day_times(
        lat=25.0330, lon=121.5654, dt=dt, tz_offset=8.0
    )

    assert day_times.sunrise is not None
    assert day_times.sunset is not None
    assert day_times.solar_noon is not None
    # 驗證日出在 05:00~06:30 之間，日落在 17:30~19:00 之間
    sr_h = int(day_times.sunrise.split(":")[0])
    ss_h = int(day_times.sunset.split(":")[0])
    assert 4 <= sr_h <= 7
    assert 17 <= ss_h <= 19


def test_moon_position_calculation():
    """測試月相與引潮力特徵"""
    dt = datetime(2026, 9, 8, 12, 0, 0)
    moon = SolarTideCalculator.calculate_moon_position(dt, tz_offset=8.0)

    assert 0.0 <= moon.phase_angle <= 360.0
    assert 0.0 <= moon.illumination_pct <= 100.0
    assert 0.0 <= moon.age_days <= 29.54
    assert len(moon.phase_name) > 0


def test_tide_status_wave_series():
    """測試潮汐調和模型波形與極值"""
    dt = datetime(2026, 9, 8, 12, 0, 0)
    tide = SolarTideCalculator.calculate_tide_status(
        lat=25.1824, lon=121.4116, dt=dt, tz_offset=8.0
    )

    assert -5.0 <= tide.current_height <= 5.0
    assert tide.trend in ["flood", "ebb"]
    assert len(tide.wave_series) >= 90  # 過去 6 小時至未來 18 小時點集
    assert tide.tide_type in ["spring", "neap", "normal"]


def test_manager_calculate():
    """測試管理器整合解算"""
    req = SolarTideCalculationRequest(
        latitude=22.6148,
        longitude=120.2736,
        location_name="高雄港",
        timezone_offset=8.0,
        datetime_iso="2026-09-08T15:30:00+08:00",
    )
    res = solar_tide_manager.calculate(req)

    assert res.location.name == "高雄港"
    assert res.solar.azimuth >= 0.0
    assert len(res.sun_path) == 48  # 24h 每 30 分鐘 1 點
    assert res.is_live_now is False


def test_api_locations_endpoint(client):
    """測試 API 取得地點列表"""
    resp = client.get("/api/solartide/locations")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 5
    assert any(loc["name"].startswith("📍 電腦目前") for loc in data)


def test_api_calculate_endpoint(client):
    """測試 API 計算日潮星象"""
    payload = {
        "latitude": 25.1824,
        "longitude": 121.4116,
        "location_name": "淡水漁人碼頭",
        "timezone_offset": 8.0,
    }
    resp = client.post("/api/solartide/calculate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "solar" in data
    assert "moon" in data
    assert "tide" in data
    assert "day_times" in data
    assert "sun_path" in data


def test_api_calculate_quick_get(client):
    """測試 GET 快速計算接口"""
    resp = client.get("/api/solartide/calculate_quick?lat=25.033&lon=121.565&name=Taipei&span_days=7")
    assert resp.status_code == 200
    data = resp.json()
    assert data["location"]["name"] == "Taipei"
    assert -90.0 <= data["solar"]["altitude"] <= 90.0
    assert data["tide"]["span_days"] == 7
    assert len(data["tide"]["wave_series"]) >= 100


def test_tide_status_multi_span_days():
    """測試多尺度跨度 (1, 7, 30天) 之資料點數與極限"""
    dt = datetime(2026, 9, 8, 12, 0, 0)
    # 7 天跨度
    tide_7d = SolarTideCalculator.calculate_tide_status(
        lat=25.1824, lon=121.4116, dt=dt, tz_offset=8.0, span_days=7
    )
    assert tide_7d.span_days == 7
    assert len(tide_7d.wave_series) >= 140

    # 30 天跨度 (月度大潮小潮完整週期)
    tide_30d = SolarTideCalculator.calculate_tide_status(
        lat=25.1824, lon=121.4116, dt=dt, tz_offset=8.0, span_days=30
    )
    assert tide_30d.span_days == 30
    assert len(tide_30d.wave_series) >= 200


def test_weather_service_and_caching():
    """測試天氣服務解算、WMO 代碼解析與快取"""
    from tools.solar_tide.weather import WeatherService

    w = WeatherService.get_weather(25.033, 121.565)
    assert -50.0 <= w.temperature <= 60.0
    assert 0.0 <= w.humidity <= 100.0
    assert len(w.condition) > 0
    assert len(w.condition_desc) > 0
    assert len(w.detail_type) > 0

    # 驗證快取命中 (相同經緯度立即再查應直接命中記憶體快取)
    w_cached = WeatherService.get_weather(25.033, 121.565)
    assert w_cached.temperature == w.temperature


def test_weather_fallback_model():
    """測試離線備援氣候生成"""
    from tools.solar_tide.weather import WeatherService

    fallback = WeatherService._generate_fallback_weather(25.0, 121.5)
    assert fallback.is_cached is True
    assert fallback.temperature > 0
    assert fallback.humidity == 72.0


def test_api_calculate_has_weather(client):
    """測試日潮計算結果包含天氣微氣候指標"""
    payload = {
        "latitude": 25.033,
        "longitude": 121.565,
        "location_name": "台北",
        "timezone_offset": 8.0,
    }
    resp = client.post("/api/solartide/calculate", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert "weather" in data
    assert data["weather"] is not None
    assert "temperature" in data["weather"]
    assert "apparent_temperature" in data["weather"]
    assert "detail_type" in data["weather"]



