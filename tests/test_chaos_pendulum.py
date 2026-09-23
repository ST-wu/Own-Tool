import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from main import app
from tools.chaos_pendulum.presets import THEMES, PRESETS
from tools.chaos_pendulum.models import PendulumPreset, ColorTheme


@pytest.fixture
def client():
    return TestClient(app)


def test_pendulum_themes_preset_integrity():
    """驗證內建光譜主題與動力學預設配置的完整性與數值邊界"""
    assert len(THEMES) >= 5
    assert "cyber_aurora" in THEMES
    assert "solar_amber" in THEMES
    assert "monochrome_ink" in THEMES

    for theme in THEMES.values():
        assert isinstance(theme, ColorTheme)
        assert theme.id
        assert theme.background.startswith("#")
        assert len(theme.trail_colors) >= 2

    assert len(PRESETS) >= 5
    for preset in PRESETS:
        assert isinstance(preset, PendulumPreset)
        assert 2 <= preset.num_links <= 6
        assert 0.1 <= preset.speed <= 5.0
        assert 0.0 <= preset.damping <= 0.01
        assert 1 <= preset.swarm_count <= 50
        assert 0.8 <= preset.trail_persistence <= 0.999
        assert preset.theme_id in THEMES


def test_pendulum_endpoints(client):
    """驗證混沌多連擺 FastAPI 路由端點"""
    # 1. 獨立頁面首頁
    res_page = client.get("/pendulum")
    assert res_page.status_code == 200
    assert "text/html" in res_page.headers.get("content-type", "")
    assert "CHAOS PENDULUM" in res_page.text
    assert "main-canvas" in res_page.text

    # 2. 獲取主題 API
    res_themes = client.get("/api/v1/pendulum/themes")
    assert res_themes.status_code == 200
    themes_data = res_themes.json()
    assert len(themes_data) >= 5
    assert any(t["id"] == "cyber_aurora" for t in themes_data)

    # 3. 獲取預設配置 API
    res_presets = client.get("/api/v1/pendulum/presets")
    assert res_presets.status_code == 200
    presets_data = res_presets.json()
    assert len(presets_data) >= 5
    assert any(p["id"] == "butterfly_swarm" for p in presets_data)


def test_static_assets_exist():
    """驗證混沌多連擺專屬 CSS 與 JS 檔案存在且非空"""
    css_path = Path("web/static/css/pendulum.css")
    js_path = Path("web/static/js/pendulum.js")
    html_path = Path("web/pendulum.html")

    assert html_path.exists() and html_path.stat().st_size > 0
    assert css_path.exists() and css_path.stat().st_size > 0
    assert js_path.exists() and js_path.stat().st_size > 0
