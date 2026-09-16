/**
 * 日潮星象儀 (SolarTide / HelioTide) 前端核心邏輯 (極致效能與逼真天氣大氣升級版)
 * 1. 物理粒子大氣系統 (靜態物件池 Zero-GC、單批 Draw Call、Visibility API 智能休眠)
 * 2. 多層次細緻天氣光影 (晴空日暈/卷雲/立體積雲/陰霾鉛灰/起霧/細雨/暴雨/雷電/飛雪/暴風雪)
 * 3. 即時大氣微氣候指標 (氣溫/體感/濕度/風速風向/紫外線/氣壓)
 * 4. Windows 桌面壁紙即時同步 (原生毫秒級 API、定時同步、一鍵還原)
 * 5. 地平線天頂全景透視 (東/南/西/北/360°全景與滑鼠拖曳轉向)
 * 6. 多尺度潮汐波動長圖 (1日/3日/7日/14日/30日)
 */

(function () {
  'use strict';

  // 狀態管理
  const state = {
    isInitialized: false,      // 防重入鎖
    location: {
      name: '淡水漁人碼頭 (新北)',
      latitude: 25.1824,
      longitude: 121.4116,
      timezone_offset: 8.0,
      is_current_device: false,
    },
    // 時間狀態
    isLive: true,
    simulatedDate: new Date(),
    isPlaying: false,
    playSpeed: 60,
    playTimer: null,
    liveClockTimer: null,
    fetchDebounceTimer: null,

    // 視角狀態 (地面人體視角)
    viewAngle: 'south',
    viewHeadingDeg: 180,
    isDraggingView: false,
    dragStartX: 0,
    dragStartHeading: 180,

    // 潮汐跨度狀態
    spanDays: 1,

    // 天氣與大氣粒子系統狀態
    activeDetailType: 'clear_sun', // 自動連動真實微氣候之細部等級
    isAnimRunning: false,
    animFrameId: null,
    lastFrameTime: 0,


    // 後端回傳數據快取
    data: null,
    locationsList: [],

    // 靜態星空點 (避免每幀重算)
    stars: [],
  };

  // 生成固定星空
  for (let i = 0; i < 80; i++) {
    state.stars.push({
      xNorm: Math.random(),
      yNorm: Math.random() * 0.75,
      radius: Math.random() * 1.5 + 0.5,
      alpha: Math.random() * 0.7 + 0.3,
    });
  }

  // ---------------------------------------------------------------------------
  // 物理粒子大氣靜態池 (Object Pools - Zero GC 零垃圾回收停頓)
  // ---------------------------------------------------------------------------
  const particles = {
    // 雨滴池 (固定 80 顆)
    rain: Array.from({ length: 80 }, () => ({
      x: Math.random() * 800,
      y: Math.random() * 400 - 400,
      vy: 12 + Math.random() * 6,
      vx: -1.5,
      len: 12 + Math.random() * 10,
      alpha: 0.35 + Math.random() * 0.3,
    })),

    // 水面水花漣漪池 (固定 15 個)
    ripples: Array.from({ length: 15 }, () => ({
      x: 0,
      y: 0,
      r: 0,
      maxR: 12,
      alpha: 0,
      active: false,
    })),

    // 雪花池 (固定 35 朵)
    snow: Array.from({ length: 35 }, () => ({
      x: Math.random() * 800,
      y: Math.random() * 400 - 400,
      r: 1.2 + Math.random() * 2.2,
      vy: 0.8 + Math.random() * 1.2,
      vx: 0,
      phase: Math.random() * Math.PI * 2,
      swingAmp: 0.8 + Math.random() * 1.2,
      swingSpeed: 0.02 + Math.random() * 0.03,
      alpha: 0.45 + Math.random() * 0.45,
    })),

    // 霧氣浮動層 (固定 3 片大橢圓)
    fog: [
      { xNorm: 0.2, yNorm: 0.72, rx: 260, ry: 45, alpha: 0.28, vx: 0.08 },
      { xNorm: 0.65, yNorm: 0.70, rx: 320, ry: 55, alpha: 0.22, vx: -0.06 },
      { xNorm: 0.85, yNorm: 0.74, rx: 220, ry: 40, alpha: 0.25, vx: 0.07 },
    ],

    // 3D 立體積雲/卷雲層 (固定 5 朵，自適應漂移)
    clouds: [
      { x: 60, y: 55, scale: 1.0, speed: 0.15, alpha: 0.85, type: 'cumulus' },
      { x: 240, y: 80, scale: 0.75, speed: 0.10, alpha: 0.75, type: 'cumulus' },
      { x: 420, y: 45, scale: 1.2, speed: 0.18, alpha: 0.90, type: 'cumulus' },
      { x: 150, y: 30, scale: 1.4, speed: 0.06, alpha: 0.45, type: 'cirrus' },
      { x: 380, y: 25, scale: 1.1, speed: 0.05, alpha: 0.40, type: 'cirrus' },
    ],

    // 雷電系統
    lightning: {
      active: false,
      timer: 0,
      cooldown: 180,
      flashAlpha: 0,
      segments: [],
    },

    // 晴空旋轉日光光束
    sunRayAngle: 0,
  };

  // DOM 元素引用快取
  const dom = {};

  function initDOM() {
    dom.container = document.getElementById('view-solartide-container');
    dom.backBtn = document.getElementById('solartide-back-to-hub-btn');

    // 地點控制
    dom.selLocation = document.getElementById('sel-st-location');
    dom.btnDetectLocation = document.getElementById('btn-st-detect-location');
    dom.inputLat = document.getElementById('input-st-lat');
    dom.inputLon = document.getElementById('input-st-lon');
    dom.inputLocName = document.getElementById('input-st-loc-name');
    dom.btnApplyCoord = document.getElementById('btn-st-apply-coord');
    dom.currentLocBadge = document.getElementById('st-current-loc-badge');

    // 時間旅行控制
    dom.btnLiveNow = document.getElementById('btn-st-now');
    dom.btnPlayPause = document.getElementById('btn-st-play');
    dom.btnPrevHour = document.getElementById('btn-st-prev-hour');
    dom.btnNextHour = document.getElementById('btn-st-next-hour');
    dom.selPlaySpeed = document.getElementById('sel-st-speed');
    dom.sliderTime = document.getElementById('slider-st-time');
    dom.inputDatetime = document.getElementById('input-st-datetime');
    dom.timeModeBadge = document.getElementById('st-time-mode-badge');
    dom.clockDisplay = document.getElementById('st-clock-display');


    // 核心指標與光影卡片
    dom.sunAltVal = document.getElementById('st-sun-alt-val');
    dom.sunAzVal = document.getElementById('st-sun-az-val');
    dom.sunPhaseText = document.getElementById('st-sun-phase-text');
    dom.tideHeightVal = document.getElementById('st-tide-height-val');
    dom.tideTrendBadge = document.getElementById('st-tide-trend-badge');
    dom.tideTypeBadge = document.getElementById('st-tide-type-badge');
    dom.nextTideText = document.getElementById('st-next-tide-text');
    dom.moonPhaseText = document.getElementById('st-moon-phase-text');
    dom.moonIllumText = document.getElementById('st-moon-illum-text');
    dom.moonAgeText = document.getElementById('st-moon-age-text');
    dom.harvestStatus = document.getElementById('st-harvest-status');

    // 微氣候指標卡片
    dom.weatherTemp = document.getElementById('st-weather-temp');
    dom.weatherAppTemp = document.getElementById('st-weather-app-temp');
    dom.weatherConditionBadge = document.getElementById('st-weather-condition-badge');
    dom.weatherHumidity = document.getElementById('st-weather-humidity');
    dom.weatherWind = document.getElementById('st-weather-wind');
    dom.weatherWindDir = document.getElementById('st-weather-wind-dir');
    dom.weatherUv = document.getElementById('st-weather-uv');

    // 太陽重要節點
    dom.timeSunrise = document.getElementById('st-time-sunrise');
    dom.timeSunset = document.getElementById('st-time-sunset');
    dom.timeNoon = document.getElementById('st-time-noon');
    dom.timeGoldenHour = document.getElementById('st-time-golden-hour');
    dom.timeBlueHour = document.getElementById('st-time-blue-hour');

    // 畫布 Canvas
    dom.canvasSkyDome = document.getElementById('canvas-st-sky-dome');
    dom.canvasTideWave = document.getElementById('canvas-st-tide-wave');
  }

  // ---------------------------------------------------------------------------
  // 1. 初始化與網路請求
  // ---------------------------------------------------------------------------
  async function init() {
    initDOM();
    if (!dom.container) return;

    if (!state.isInitialized) {
      bindEvents();
      await loadLocations();
      detectDeviceLocation(true);
      startLiveClock();
      setupVisibilityListener();
      startWeatherLoop();
      state.isInitialized = true;
    } else {
      fetchCalculation();
      startWeatherLoop();
    }
  }

  // 載入預設港口景點清單
  async function loadLocations() {
    try {
      const res = await fetch('/api/solartide/locations');
      if (res.ok) {
        state.locationsList = await res.json();
        renderLocationSelect();
      }
    } catch (e) {
      console.warn('[SolarTide] 無法取得預設港口列表:', e);
    }
  }

  function renderLocationSelect() {
    if (!dom.selLocation) return;
    dom.selLocation.innerHTML = '';
    state.locationsList.forEach((loc) => {
      const opt = document.createElement('option');
      opt.value = `${loc.latitude},${loc.longitude}`;
      opt.textContent = loc.name;
      opt.dataset.name = loc.name;
      opt.dataset.tz = loc.timezone_offset;
      dom.selLocation.appendChild(opt);
    });

    dom.selLocation.value = `${state.location.latitude},${state.location.longitude}`;
    updateCoordInputs();
  }

  // 偵測電腦目前所在 GPS 定位
  function detectDeviceLocation(silent = false) {
    if ('geolocation' in navigator) {
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const lat = parseFloat(pos.coords.latitude.toFixed(4));
          const lon = parseFloat(pos.coords.longitude.toFixed(4));
          state.location = {
            name: '📍 電腦目前位置 (GPS 偵測)',
            latitude: lat,
            longitude: lon,
            timezone_offset: -new Date().getTimezoneOffset() / 60.0,
            is_current_device: true,
          };
          updateCoordInputs();
          if (dom.currentLocBadge) {
            dom.currentLocBadge.textContent = state.location.name;
            dom.currentLocBadge.classList.add('active');
          }
          fetchCalculation();
        },
        (err) => {
          if (!silent) {
            alert('無法獲取本機精確定位 (可能未允許瀏覽器定位授權)，已為您保留既有位置。');
          }
          fetchCalculation();
        },
        { timeout: 6000, enableHighAccuracy: true }
      );
    } else {
      fetchCalculation();
    }
  }

  function updateCoordInputs() {
    if (dom.inputLat) dom.inputLat.value = state.location.latitude;
    if (dom.inputLon) dom.inputLon.value = state.location.longitude;
    if (dom.inputLocName) dom.inputLocName.value = state.location.name;
  }

  // ---------------------------------------------------------------------------
  // 2. 核心運算發送與防抖 (Debounced Calculation)
  // ---------------------------------------------------------------------------
  function fetchCalculation() {
    clearTimeout(state.fetchDebounceTimer);
    state.fetchDebounceTimer = setTimeout(async () => {
      await doCalculation();
    }, 40);
  }

  async function doCalculation() {
    const payload = {
      latitude: state.location.latitude,
      longitude: state.location.longitude,
      location_name: state.location.name,
      timezone_offset: state.location.timezone_offset,
      datetime_iso: state.isLive ? null : state.simulatedDate.toISOString(),
      span_days: state.spanDays,
    };

    try {
      const res = await fetch('/api/solartide/calculate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (res.ok) {
        state.data = await res.json();
        updateActiveWeatherDetail();
        renderSummaryCards(state.data);
        drawTideWave(state.data);
      }
    } catch (err) {
      console.error('[SolarTide] 計算失敗:', err);
    }
  }

  // 依據後端即時 API 回傳自動連動天氣粒子等級
  function updateActiveWeatherDetail() {
    if (state.data && state.data.weather) {
      state.activeDetailType = state.data.weather.detail_type || 'clear_sun';
    } else {
      state.activeDetailType = 'clear_sun';
    }
  }


  // ---------------------------------------------------------------------------
  // 3. 事件綁定 (Event Listeners)
  // ---------------------------------------------------------------------------
  function bindEvents() {
    // 返回主選單
    if (dom.backBtn) {
      dom.backBtn.addEventListener('click', () => {
        window.location.hash = '';
        stopWeatherLoop();
      });
    }

    // 重新偵測目前位置
    if (dom.btnDetectLocation) {
      dom.btnDetectLocation.addEventListener('click', () => {
        detectDeviceLocation(false);
      });
    }

    // 下拉選單切換地點
    if (dom.selLocation) {
      dom.selLocation.addEventListener('change', (e) => {
        const selected = dom.selLocation.selectedOptions[0];
        const [lat, lon] = e.target.value.split(',').map(Number);
        state.location.latitude = lat;
        state.location.longitude = lon;
        state.location.name = selected.dataset.name || '自訂港口';
        state.location.timezone_offset = parseFloat(selected.dataset.tz || '8');
        state.location.is_current_device = false;
        if (dom.currentLocBadge) {
          dom.currentLocBadge.textContent = state.location.name;
          dom.currentLocBadge.classList.remove('active');
        }
        updateCoordInputs();
        fetchCalculation();
      });
    }

    // 手動套用經緯度
    if (dom.btnApplyCoord) {
      dom.btnApplyCoord.addEventListener('click', () => {
        const lat = parseFloat(dom.inputLat.value);
        const lon = parseFloat(dom.inputLon.value);
        const name = dom.inputLocName.value.trim() || `自訂座標 (${lat}, ${lon})`;

        if (isNaN(lat) || lat < -90 || lat > 90 || isNaN(lon) || lon < -180 || lon > 180) {
          alert('請輸入有效之經緯度數值 (緯度 -90~90，經度 -180~180)');
          return;
        }

        state.location.latitude = lat;
        state.location.longitude = lon;
        state.location.name = name;
        state.location.is_current_device = false;
        if (dom.currentLocBadge) {
          dom.currentLocBadge.textContent = name;
        }
        fetchCalculation();
      });
    }

    // 回到現在 (NOW) 按鈕
    if (dom.btnLiveNow) {
      dom.btnLiveNow.addEventListener('click', () => {
        state.isLive = true;
        state.isPlaying = false;
        clearInterval(state.playTimer);
        updatePlayButtonUI();
        state.simulatedDate = new Date();
        updateTimeUI();
        fetchCalculation();
      });
    }

    // 24 小時時間滑桿拖動
    if (dom.sliderTime) {
      dom.sliderTime.addEventListener('input', (e) => {
        switchToSimulatedMode();
        const minutes = parseInt(e.target.value, 10);
        const d = new Date(state.simulatedDate);
        d.setHours(Math.floor(minutes / 60), minutes % 60, 0, 0);
        state.simulatedDate = d;
        updateTimeUI();
        fetchCalculation();
      });
    }

    // 時間日期輸入器變更
    if (dom.inputDatetime) {
      dom.inputDatetime.addEventListener('change', (e) => {
        if (e.target.value) {
          switchToSimulatedMode();
          state.simulatedDate = new Date(e.target.value);
          updateTimeUI();
          fetchCalculation();
        }
      });
    }

    // 快退 1 小時
    if (dom.btnPrevHour) {
      dom.btnPrevHour.addEventListener('click', () => {
        switchToSimulatedMode();
        state.simulatedDate = new Date(state.simulatedDate.getTime() - 3600 * 1000);
        updateTimeUI();
        fetchCalculation();
      });
    }

    // 快進 1 小時
    if (dom.btnNextHour) {
      dom.btnNextHour.addEventListener('click', () => {
        switchToSimulatedMode();
        state.simulatedDate = new Date(state.simulatedDate.getTime() + 3600 * 1000);
        updateTimeUI();
        fetchCalculation();
      });
    }

    // 播放 / 暫停按鈕
    if (dom.btnPlayPause) {
      dom.btnPlayPause.addEventListener('click', () => {
        togglePlayPause();
      });
    }

    // 播放速度切換
    if (dom.selPlaySpeed) {
      dom.selPlaySpeed.addEventListener('change', (e) => {
        state.playSpeed = parseInt(e.target.value, 10);
        if (state.isPlaying) {
          clearInterval(state.playTimer);
          startPlayLoop();
        }
      });
    }

    // 視角切換按鈕 (南/東/西/北/360°)
    document.querySelectorAll('.st-chip-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        document.querySelectorAll('.st-chip-btn').forEach((b) => b.classList.remove('active'));
        e.target.classList.add('active');
        const view = e.target.dataset.view;
        state.viewAngle = view;
        if (view === 'south') state.viewHeadingDeg = 180;
        else if (view === 'east') state.viewHeadingDeg = 90;
        else if (view === 'west') state.viewHeadingDeg = 270;
        else if (view === 'north') state.viewHeadingDeg = 0;
        else if (view === 'pano') state.viewHeadingDeg = 180;
      });
    });


    // 潮汐跨度切換按鈕 (1日/3日/7日/14日/30日)
    document.querySelectorAll('.st-span-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        document.querySelectorAll('.st-span-btn').forEach((b) => b.classList.remove('active'));
        e.target.classList.add('active');
        state.spanDays = parseInt(e.target.dataset.span, 10) || 1;
        fetchCalculation();
      });
    });

    // 滑鼠在地面畫布上拖曳旋轉視野
    if (dom.canvasSkyDome) {
      dom.canvasSkyDome.addEventListener('mousedown', (e) => {
        if (state.viewAngle === 'pano') return;
        state.isDraggingView = true;
        state.dragStartX = e.clientX;
        state.dragStartHeading = state.viewHeadingDeg;
      });

      window.addEventListener('mousemove', (e) => {
        if (!state.isDraggingView) return;
        const dx = e.clientX - state.dragStartX;
        const degChange = -(dx / 3.0);
        state.viewHeadingDeg = (state.dragStartHeading + degChange + 360) % 360;
      });

      window.addEventListener('mouseup', () => {
        state.isDraggingView = false;
      });
    }
  }

  // ---------------------------------------------------------------------------
  // 4. 動態控制與 Visibility API 智能節能 (Performance Core)
  // ---------------------------------------------------------------------------
  function setupVisibilityListener() {
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) {
        stopWeatherLoop();
      } else {
        if (dom.container && dom.container.classList.contains('active')) {
          startWeatherLoop();
        }
      }
    });
  }

  function startWeatherLoop() {
    if (state.isAnimRunning) return;
    state.isAnimRunning = true;
    state.lastFrameTime = performance.now();

    function loop(time) {
      if (!state.isAnimRunning) return;

      // 若非前景分頁或容器未展示，自動休眠
      if (document.hidden || !dom.container || !dom.container.classList.contains('active')) {
        state.isAnimRunning = false;
        return;
      }

      const dt = Math.min(32, time - state.lastFrameTime);
      state.lastFrameTime = time;

      if (state.data) {
        drawGroundSkyView(state.data, dt);
      }

      state.animFrameId = requestAnimationFrame(loop);
    }

    state.animFrameId = requestAnimationFrame(loop);
  }

  function stopWeatherLoop() {
    state.isAnimRunning = false;
    if (state.animFrameId) {
      cancelAnimationFrame(state.animFrameId);
      state.animFrameId = null;
    }
  }

  function switchToSimulatedMode() {
    if (state.isLive) {
      state.isLive = false;
      if (dom.timeModeBadge) {
        dom.timeModeBadge.textContent = '時間旅行模擬 (Simulated)';
        dom.timeModeBadge.className = 'st-badge st-badge-simulation';
      }
    }
  }

  function togglePlayPause() {
    if (state.isPlaying) {
      state.isPlaying = false;
      clearInterval(state.playTimer);
      state.playTimer = null;
    } else {
      switchToSimulatedMode();
      state.isPlaying = true;
      startPlayLoop();
    }
    updatePlayButtonUI();
  }

  function startPlayLoop() {
    const frameIntervalMs = 50;
    state.playTimer = setInterval(() => {
      const advancedMs = (state.playSpeed * 1000) * (frameIntervalMs / 1000);
      state.simulatedDate = new Date(state.simulatedDate.getTime() + advancedMs);
      updateTimeUI();
      fetchCalculation();
    }, frameIntervalMs);
  }

  function updatePlayButtonUI() {
    if (!dom.btnPlayPause) return;
    if (state.isPlaying) {
      dom.btnPlayPause.textContent = '⏸️ 暫停模擬';
      dom.btnPlayPause.className = 'btn btn-sm btn-secondary';
    } else {
      dom.btnPlayPause.textContent = '▶ 播放模擬';
      dom.btnPlayPause.className = 'btn btn-sm btn-primary';
    }
  }

  function startLiveClock() {
    let tickCount = 0;
    state.liveClockTimer = setInterval(() => {
      if (state.isLive && !state.isPlaying) {
        state.simulatedDate = new Date();
        updateTimeUI();
        tickCount++;
        if (tickCount % 10 === 0) {
          fetchCalculation();
        }
      }
    }, 1000);
  }

  function updateTimeUI() {
    const d = state.simulatedDate;
    const pad = (n) => String(n).padStart(2, '0');
    const yyyy = d.getFullYear();
    const mm = pad(d.getMonth() + 1);
    const dd = pad(d.getDate());
    const hh = pad(d.getHours());
    const min = pad(d.getMinutes());
    const ss = pad(d.getSeconds());

    if (dom.clockDisplay) {
      dom.clockDisplay.textContent = `${yyyy}-${mm}-${dd} ${hh}:${min}:${ss}`;
    }
    if (dom.sliderTime) {
      dom.sliderTime.value = d.getHours() * 60 + d.getMinutes();
    }
    if (dom.inputDatetime) {
      dom.inputDatetime.value = `${yyyy}-${mm}-${dd}T${hh}:${min}`;
    }
    if (state.isLive && dom.timeModeBadge) {
      dom.timeModeBadge.textContent = '即時電腦時鐘 (Live)';
      dom.timeModeBadge.className = 'st-badge st-badge-live';
    }
  }


  // ---------------------------------------------------------------------------
  // 6. 綜合數據卡片與微氣候指標更新
  // ---------------------------------------------------------------------------
  function renderSummaryCards(d) {
    if (dom.sunAltVal) dom.sunAltVal.textContent = `${d.solar.altitude.toFixed(1)}°`;
    if (dom.sunAzVal) dom.sunAzVal.textContent = `${d.solar.azimuth.toFixed(1)}°`;
    if (dom.sunPhaseText) dom.sunPhaseText.textContent = d.solar.phase_name;

    if (dom.tideHeightVal) {
      const sign = d.tide.current_height >= 0 ? '+' : '';
      dom.tideHeightVal.textContent = `${sign}${d.tide.current_height.toFixed(2)} m`;
    }

    if (dom.tideTrendBadge) {
      if (d.tide.trend === 'flood') {
        dom.tideTrendBadge.textContent = '漲潮中 ⇡';
        dom.tideTrendBadge.className = 'st-pill st-pill-flood';
      } else {
        dom.tideTrendBadge.textContent = '退潮中 ⇣';
        dom.tideTrendBadge.className = 'st-pill st-pill-ebb';
      }
    }

    if (dom.tideTypeBadge) {
      if (d.tide.tide_type === 'spring') {
        dom.tideTypeBadge.textContent = '大潮 (Spring Tide 🌊)';
        dom.tideTypeBadge.className = 'st-pill st-pill-spring';
      } else if (d.tide.tide_type === 'neap') {
        dom.tideTypeBadge.textContent = '小潮 (Neap Tide 🏖️)';
        dom.tideTypeBadge.className = 'st-pill st-pill-neap';
      } else {
        dom.tideTypeBadge.textContent = '一般中潮 (Normal)';
        dom.tideTypeBadge.className = 'st-pill st-pill-normal';
      }
    }

    if (dom.nextTideText) {
      let highText = d.tide.next_high_tide
        ? `滿潮 ${d.tide.next_high_tide.time} (${d.tide.next_high_tide.height >= 0 ? '+' : ''}${d.tide.next_high_tide.height.toFixed(2)}m)`
        : '--';
      let lowText = d.tide.next_low_tide
        ? `乾潮 ${d.tide.next_low_tide.time} (${d.tide.next_low_tide.height >= 0 ? '+' : ''}${d.tide.next_low_tide.height.toFixed(2)}m)`
        : '--';
      dom.nextTideText.textContent = `🔺 ${highText}  |  🔻 ${lowText}`;
    }

    if (dom.moonPhaseText) dom.moonPhaseText.textContent = d.moon.phase_name;
    if (dom.moonIllumText) dom.moonIllumText.textContent = `受光率: ${d.moon.illumination_pct}%`;
    if (dom.moonAgeText) dom.moonAgeText.textContent = `月齡: ${d.moon.age_days} 天`;

    // 趕海安全窗口
    if (dom.harvestStatus) {
      if (d.tide.harvest_window) {
        dom.harvestStatus.textContent = '🟢 最佳趕海/潮間帶採集窗口 (乾潮前後安全時段)';
        dom.harvestStatus.className = 'st-alert st-alert-success';
      } else {
        dom.harvestStatus.textContent = '🟡 潮位較高或水流湍急，下海請注意潮水漲落安全';
        dom.harvestStatus.className = 'st-alert st-alert-warning';
      }
    }

    // 微氣候指標
    if (d.weather) {
      const w = d.weather;
      if (dom.weatherTemp) dom.weatherTemp.textContent = `${w.temperature.toFixed(1)}°C`;
      if (dom.weatherAppTemp) dom.weatherAppTemp.textContent = `體感 ${w.apparent_temperature.toFixed(1)}°C`;
      if (dom.weatherConditionBadge) {
        dom.weatherConditionBadge.textContent = w.condition_desc;
      }
      if (dom.weatherHumidity) dom.weatherHumidity.textContent = `${w.humidity.toFixed(0)}%`;
      if (dom.weatherWind) dom.weatherWind.textContent = `${w.wind_speed_kmh.toFixed(1)} km/h`;
      if (dom.weatherWindDir) dom.weatherWindDir.textContent = `${w.wind_direction_deg.toFixed(0)}°`;
      if (dom.weatherUv) dom.weatherUv.textContent = `${w.uv_index.toFixed(1)}`;
    }

    // 太陽時刻
    if (dom.timeSunrise) dom.timeSunrise.textContent = d.day_times.sunrise || '--:--';
    if (dom.timeSunset) dom.timeSunset.textContent = d.day_times.sunset || '--:--';
    if (dom.timeNoon) dom.timeNoon.textContent = d.day_times.solar_noon || '--:--';
    if (dom.timeGoldenHour) dom.timeGoldenHour.textContent = d.day_times.golden_hour_evening || '--';
    if (dom.timeBlueHour) dom.timeBlueHour.textContent = d.day_times.blue_hour_evening || '--';
  }

  // ---------------------------------------------------------------------------
  // 7. 站在地面上的地平線天頂透視圖與大氣粒子渲染
  // ---------------------------------------------------------------------------
  function drawGroundSkyView(d, dt = 16) {
    const canvas = dom.canvasSkyDome;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    const width = canvas.width = canvas.parentElement.clientWidth || 560;
    const height = canvas.height = 340;

    const horizonY = height * 0.72;
    const skyH = horizonY;
    const groundH = height - horizonY;
    const alt = d.solar.altitude;
    const weatherType = state.activeDetailType;

    ctx.clearRect(0, 0, width, height);

    // 1. 天空背景光影漸層色 (受時間仰角與陰霾厚度調節)
    let skyGrad = ctx.createLinearGradient(0, 0, 0, horizonY);
    const isOvercast = weatherType === 'overcast' || weatherType === 'heavy_rain' || weatherType === 'thunderstorm';
    const isFog = weatherType === 'fog' || weatherType === 'dense_fog';

    if (isOvercast) {
      // 陰雨鉛灰天空
      skyGrad.addColorStop(0, '#1e293b');
      skyGrad.addColorStop(0.5, '#334155');
      skyGrad.addColorStop(1, '#475569');
    } else if (isFog) {
      // 霧濛柔和乳白灰
      skyGrad.addColorStop(0, '#475569');
      skyGrad.addColorStop(0.5, '#64748b');
      skyGrad.addColorStop(1, '#94a3b8');
    } else if (alt > 6) {
      // 晴天白晝
      skyGrad.addColorStop(0, '#0284c7');
      skyGrad.addColorStop(0.7, '#38bdf8');
      skyGrad.addColorStop(1, '#bae6fd');
    } else if (alt >= 0) {
      // 晨昏金紅暖陽
      skyGrad.addColorStop(0, '#1e1b4b');
      skyGrad.addColorStop(0.35, '#991b1b');
      skyGrad.addColorStop(0.7, '#ea580c');
      skyGrad.addColorStop(1, '#fef08a');
    } else if (alt >= -6) {
      // 暮光藍調時刻
      skyGrad.addColorStop(0, '#090d16');
      skyGrad.addColorStop(0.5, '#1e1b4b');
      skyGrad.addColorStop(0.85, '#312e81');
      skyGrad.addColorStop(1, '#7c3aed');
    } else {
      // 深夜星空
      skyGrad.addColorStop(0, '#030712');
      skyGrad.addColorStop(0.7, '#090d16');
      skyGrad.addColorStop(1, '#0f172a');
    }

    ctx.fillStyle = skyGrad;
    ctx.fillRect(0, 0, width, horizonY);

    // 2. 夜晚璀璨繁星 (陰雨霧天自動隱蔽)
    if (alt < -2 && !isOvercast && !isFog) {
      const starAlphaFactor = Math.min(1, Math.max(0, (-alt - 2) / 6.0));
      ctx.save();
      state.stars.forEach((s) => {
        ctx.beginPath();
        ctx.arc(s.xNorm * width, s.yNorm * skyH, s.radius, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(255, 255, 255, ${s.alpha * starAlphaFactor})`;
        ctx.fill();
      });
      ctx.restore();
    }

    // 3. 投影轉換系統
    const isPano = state.viewAngle === 'pano';
    const fov = 130.0;
    const centerHeading = (state.viewHeadingDeg + 360) % 360;

    function projectGround(azimuthDeg, elevationDeg) {
      let x = 0;
      let inView = true;
      if (isPano) {
        x = (azimuthDeg / 360.0) * width;
      } else {
        let diff = (azimuthDeg - centerHeading + 540) % 360 - 180;
        if (Math.abs(diff) > fov / 2 + 15) inView = false;
        x = width / 2 + (diff / (fov / 2)) * (width / 2);
      }
      const topPad = 25;
      const y = horizonY - (Math.max(-10, elevationDeg) / 90.0) * (horizonY - topPad);
      return { x, y, inView };
    }

    // 4. 全天太陽天際金色拱弧 (Sun Path Arc)
    if (d.sun_path && d.sun_path.length > 0 && !isOvercast) {
      ctx.save();
      ctx.beginPath();
      let started = false;
      d.sun_path.forEach((pt) => {
        const p = projectGround(pt.azimuth, pt.altitude);
        if (p.inView && pt.altitude >= -2) {
          if (!started) {
            ctx.moveTo(p.x, p.y);
            started = true;
          } else {
            ctx.lineTo(p.x, p.y);
          }
        }
      });
      ctx.strokeStyle = 'rgba(251, 191, 36, 0.45)';
      ctx.lineWidth = 3;
      ctx.setLineDash([4, 4]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }

    // 5. 太陽發光球體與大氣光暈
    const sunP = projectGround(d.solar.azimuth, d.solar.altitude);
    if (sunP.inView && d.solar.altitude >= -4) {
      ctx.save();
      const glowR = isOvercast ? 20 : Math.max(20, Math.min(80, 25 + Math.max(0, d.solar.altitude) * 0.7));
      const sunGrad = ctx.createRadialGradient(sunP.x, sunP.y, 4, sunP.x, sunP.y, glowR);

      if (isOvercast) {
        sunGrad.addColorStop(0, 'rgba(255, 255, 255, 0.35)');
        sunGrad.addColorStop(1, 'rgba(255, 255, 255, 0.0)');
      } else {
        sunGrad.addColorStop(0, 'rgba(254, 240, 138, 0.95)');
        sunGrad.addColorStop(0.3, 'rgba(251, 191, 36, 0.55)');
        sunGrad.addColorStop(0.7, 'rgba(245, 158, 11, 0.2)');
        sunGrad.addColorStop(1, 'rgba(245, 158, 11, 0.0)');
      }

      ctx.beginPath();
      ctx.arc(sunP.x, sunP.y, glowR, 0, Math.PI * 2);
      ctx.fillStyle = sunGrad;
      ctx.fill();

      // 晴天金色旋轉放射光束 (Sun Rays)
      if (weatherType === 'clear' || weatherType === 'clear_sun') {
        particles.sunRayAngle += 0.003;
        ctx.strokeStyle = 'rgba(254, 240, 138, 0.18)';
        ctx.lineWidth = 2.5;
        for (let i = 0; i < 4; i++) {
          const ang = particles.sunRayAngle + (i * Math.PI) / 2;
          ctx.beginPath();
          ctx.moveTo(sunP.x - Math.cos(ang) * (glowR + 10), sunP.y - Math.sin(ang) * (glowR + 10));
          ctx.lineTo(sunP.x + Math.cos(ang) * (glowR + 10), sunP.y + Math.sin(ang) * (glowR + 10));
          ctx.stroke();
        }
      }

      // 太陽核心球
      ctx.beginPath();
      ctx.arc(sunP.x, sunP.y, isOvercast ? 7 : 11, 0, Math.PI * 2);
      ctx.fillStyle = isOvercast ? '#e2e8f0' : '#fff';
      ctx.fill();
      ctx.strokeStyle = isOvercast ? '#94a3b8' : '#fbbf24';
      ctx.lineWidth = 2.5;
      ctx.stroke();

      // 太陽仰角標籤
      ctx.font = 'bold 11px Inter, sans-serif';
      ctx.fillStyle = isOvercast ? '#cbd5e1' : '#fef08a';
      ctx.textAlign = 'center';
      ctx.fillText(`☀️ 仰角 ${d.solar.altitude.toFixed(1)}°`, sunP.x, sunP.y - (isOvercast ? 14 : 18));
      ctx.restore();
    }

    // 6. 月亮相位球體
    const moonAz = (d.solar.azimuth + d.moon.phase_angle) % 360;
    const moonAlt = Math.sin((d.moon.phase_angle / 360) * Math.PI * 2) * 50;
    const moonP = projectGround(moonAz, moonAlt);
    if (moonP.inView && moonAlt >= -2 && !isOvercast) {
      ctx.save();
      ctx.beginPath();
      ctx.arc(moonP.x, moonP.y, 9, 0, Math.PI * 2);
      ctx.fillStyle = '#e2e8f0';
      ctx.fill();
      ctx.strokeStyle = '#94a3b8';
      ctx.lineWidth = 1.5;
      ctx.stroke();

      ctx.font = '10px Inter, sans-serif';
      ctx.fillStyle = '#cbd5e1';
      ctx.textAlign = 'center';
      ctx.fillText(`🌙 ${d.moon.phase_name.split(' ')[0]}`, moonP.x, moonP.y + 18);
      ctx.restore();
    }

    // 7. 雲層渲染 (晴間少雲、多雲、陰天)
    renderClouds(ctx, width, horizonY, weatherType, dt);

    // 8. 霧氣渲染 (起霧時地平線乳白漸變)
    if (isFog) {
      renderFog(ctx, width, horizonY, weatherType, dt);
    }

    // 9. 地平線山丘/海浪大地剪影 (Ground Foreground Silhouette)
    ctx.save();
    ctx.beginPath();
    ctx.moveTo(0, horizonY);
    for (let x = 0; x <= width; x += 30) {
      const hillH = Math.sin(x * 0.015) * 6 + Math.cos(x * 0.03) * 4;
      ctx.lineTo(x, horizonY - hillH);
    }
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.closePath();

    const groundGrad = ctx.createLinearGradient(0, horizonY, 0, height);
    groundGrad.addColorStop(0, '#0f172a');
    groundGrad.addColorStop(1, '#020617');
    ctx.fillStyle = groundGrad;
    ctx.fill();

    ctx.strokeStyle = isFog ? 'rgba(255, 255, 255, 0.08)' : 'rgba(255, 255, 255, 0.2)';
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.restore();

    // 10. 天氣降水粒子 (雨滴、地面漣漪、雪花、閃電)
    renderPrecipitation(ctx, width, height, horizonY, weatherType, dt);

    // 11. 地平線方位標記刻度
    renderHorizonCompass(ctx, width, height, horizonY, projectGround, centerHeading, isPano);
  }

  // ---------------------------------------------------------------------------
  // 8. 雲層與大氣霧層實體化渲染 (Batch Canvas 繪製)
  // ---------------------------------------------------------------------------
  function renderClouds(ctx, width, horizonY, weatherType, dt) {
    if (weatherType === 'clear' || weatherType === 'clear_sun') return;

    const isFew = weatherType === 'few_clouds';
    const isOvercast = weatherType === 'overcast' || weatherType === 'heavy_rain' || weatherType === 'thunderstorm';

    ctx.save();
    particles.clouds.forEach((cloud, idx) => {
      // 若是少雲模式只畫前 2 朵
      if (isFew && idx > 1) return;

      cloud.x += cloud.speed * (dt / 16);
      if (cloud.x > width + 100) cloud.x = -100;

      const scale = cloud.scale;
      const x = cloud.x;
      const y = Math.min(horizonY - 40, cloud.y);
      const alpha = isOvercast ? 0.35 : cloud.alpha;

      ctx.fillStyle = isOvercast ? `rgba(71, 85, 105, ${alpha})` : `rgba(255, 255, 255, ${alpha})`;
      ctx.beginPath();
      // 3D 蓬鬆泡泡雲外廓
      ctx.arc(x, y, 25 * scale, 0, Math.PI * 2);
      ctx.arc(x + 22 * scale, y - 10 * scale, 30 * scale, 0, Math.PI * 2);
      ctx.arc(x + 50 * scale, y - 5 * scale, 24 * scale, 0, Math.PI * 2);
      ctx.arc(x + 35 * scale, y + 8 * scale, 22 * scale, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.restore();
  }

  function renderFog(ctx, width, horizonY, weatherType, dt) {
    ctx.save();
    particles.fog.forEach((f) => {
      f.xNorm += (f.vx * (dt / 16)) / 1000;
      if (f.xNorm > 1.2) f.xNorm = -0.2;
      if (f.xNorm < -0.2) f.xNorm = 1.2;

      const cx = f.xNorm * width;
      const cy = horizonY - 10;
      const grad = ctx.createRadialGradient(cx, cy, 10, cx, cy, f.rx);
      grad.addColorStop(0, `rgba(226, 232, 240, ${f.alpha})`);
      grad.addColorStop(0.6, `rgba(203, 213, 225, ${f.alpha * 0.5})`);
      grad.addColorStop(1, 'rgba(203, 213, 225, 0)');

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.ellipse(cx, cy, f.rx, f.ry, 0, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.restore();
  }

  // ---------------------------------------------------------------------------
  // 9. 降水粒子與閃電 (零 GC 單批 Draw Call)
  // ---------------------------------------------------------------------------
  function renderPrecipitation(ctx, width, height, horizonY, weatherType, dt) {
    const isRain =
      weatherType === 'drizzle' ||
      weatherType === 'rain' ||
      weatherType === 'heavy_rain' ||
      weatherType === 'thunderstorm';

    const isSnow = weatherType === 'snow' || weatherType === 'heavy_snow';

    // 1. 雨滴與漣漪繪製
    if (isRain) {
      const isHeavy = weatherType === 'heavy_rain' || weatherType === 'thunderstorm';
      const count = weatherType === 'drizzle' ? 35 : (isHeavy ? 80 : 55);
      const speedMult = isHeavy ? 1.4 : (weatherType === 'drizzle' ? 0.7 : 1.0);

      ctx.save();
      ctx.strokeStyle = isHeavy ? 'rgba(186, 230, 253, 0.65)' : 'rgba(186, 230, 253, 0.45)';
      ctx.lineWidth = isHeavy ? 1.8 : 1.2;
      ctx.beginPath();

      for (let i = 0; i < count; i++) {
        const drop = particles.rain[i];
        drop.y += drop.vy * speedMult * (dt / 16);
        drop.x += drop.vx * (dt / 16);

        // 超出地平線產生漣漪並循環重置
        if (drop.y > horizonY + 5) {
          triggerRipple(drop.x, horizonY + Math.random() * 20);
          drop.y = -drop.len - Math.random() * 30;
          drop.x = Math.random() * (width + 100) - 50;
        }

        ctx.moveTo(drop.x, drop.y);
        ctx.lineTo(drop.x + drop.vx * 2, drop.y + drop.len * speedMult);
      }
      ctx.stroke();
      ctx.restore();

      // 地表擴散漣漪
      ctx.save();
      ctx.strokeStyle = 'rgba(186, 230, 253, 0.35)';
      ctx.lineWidth = 1;
      particles.ripples.forEach((rp) => {
        if (!rp.active) return;
        rp.r += 0.4 * (dt / 16);
        rp.alpha -= 0.02 * (dt / 16);
        if (rp.alpha <= 0) {
          rp.active = false;
        } else {
          ctx.beginPath();
          ctx.ellipse(rp.x, rp.y, rp.r * 2.5, rp.r, 0, 0, Math.PI * 2);
          ctx.stroke();
        }
      });
      ctx.restore();
    }

    // 2. 閃電特效 (Thunderstorm)
    if (weatherType === 'thunderstorm') {
      const lt = particles.lightning;
      lt.timer += dt / 16;
      if (lt.timer > lt.cooldown) {
        lt.timer = 0;
        lt.cooldown = 120 + Math.random() * 180;
        lt.flashAlpha = 0.35;
        // 生成折線分支
        lt.segments = [];
        let curX = width * 0.3 + Math.random() * (width * 0.4);
        let curY = 10;
        lt.segments.push({ x: curX, y: curY });
        while (curY < horizonY - 15) {
          curX += (Math.random() - 0.5) * 45;
          curY += 20 + Math.random() * 25;
          lt.segments.push({ x: curX, y: curY });
        }
      }

      if (lt.flashAlpha > 0) {
        // 全屏雷光
        ctx.fillStyle = `rgba(255, 255, 255, ${lt.flashAlpha})`;
        ctx.fillRect(0, 0, width, height);

        // 閃電金色/白藍折線
        ctx.save();
        ctx.strokeStyle = '#fff';
        ctx.lineWidth = 2.5;
        ctx.shadowColor = '#38bdf8';
        ctx.shadowBlur = 10;
        ctx.beginPath();
        if (lt.segments.length > 0) {
          ctx.moveTo(lt.segments[0].x, lt.segments[0].y);
          for (let s = 1; s < lt.segments.length; s++) {
            ctx.lineTo(lt.segments[s].x, lt.segments[s].y);
          }
          ctx.stroke();
        }
        ctx.restore();
        lt.flashAlpha -= 0.04 * (dt / 16);
      }
    }

    // 3. 雪花粒子 (Snow)
    if (isSnow) {
      const isBlizzard = weatherType === 'heavy_snow';
      const count = isBlizzard ? 35 : 22;
      const speedMult = isBlizzard ? 2.2 : 1.0;
      const windVx = isBlizzard ? 3.5 : 0.4;

      ctx.save();
      ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
      ctx.beginPath();

      for (let i = 0; i < count; i++) {
        const flake = particles.snow[i];
        flake.phase += flake.swingSpeed * (dt / 16);
        flake.y += flake.vy * speedMult * (dt / 16);
        flake.x += (Math.sin(flake.phase) * flake.swingAmp + windVx) * (dt / 16);

        if (flake.y > horizonY + 20 || flake.x > width + 20) {
          flake.y = -10 - Math.random() * 20;
          flake.x = Math.random() * width - (isBlizzard ? 100 : 0);
        }

        ctx.moveTo(flake.x, flake.y);
        ctx.arc(flake.x, flake.y, flake.r, 0, Math.PI * 2);
      }
      ctx.fill();
      ctx.restore();
    }
  }

  function triggerRipple(x, y) {
    for (let i = 0; i < particles.ripples.length; i++) {
      const rp = particles.ripples[i];
      if (!rp.active) {
        rp.x = x;
        rp.y = y;
        rp.r = 1;
        rp.alpha = 0.5;
        rp.active = true;
        break;
      }
    }
  }

  // 地平線方位刻度
  function renderHorizonCompass(ctx, width, height, horizonY, projectGround, centerHeading, isPano) {
    ctx.save();
    ctx.font = 'bold 11px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';

    const markers = [
      { deg: 0, label: 'N (正北)' },
      { deg: 45, label: 'NE (東北)' },
      { deg: 90, label: 'E (正東)' },
      { deg: 135, label: 'SE (東南)' },
      { deg: 180, label: 'S (正南)' },
      { deg: 225, label: 'SW (西南)' },
      { deg: 270, label: 'W (正西)' },
      { deg: 315, label: 'NW (西北)' },
      { deg: 360, label: 'N (正北)' },
    ];

    markers.forEach((m) => {
      const p = projectGround(m.deg, 0);
      if (p.x >= 15 && p.x <= width - 15) {
        ctx.beginPath();
        ctx.moveTo(p.x, horizonY - 4);
        ctx.lineTo(p.x, horizonY + 6);
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
        ctx.lineWidth = 1;
        ctx.stroke();

        ctx.fillStyle = m.deg === 0 || m.deg === 360 ? '#38bdf8' : m.deg === 180 ? '#fbbf24' : '#94a3b8';
        ctx.fillText(m.label, p.x, horizonY + 10);
      }
    });

    ctx.font = '11px Inter, sans-serif';
    ctx.fillStyle = '#64748b';
    ctx.textAlign = 'left';
    const viewName = isPano
      ? '360° 全景模式'
      : `視角朝向: ${getAzimuthDirection(centerHeading)} (${centerHeading.toFixed(0)}°) • 左右拖曳轉向`;
    ctx.fillText(`👀 ${viewName}`, 14, height - 12);
    ctx.restore();
  }

  function getAzimuthDirection(deg) {
    const directions = ['北', '東北', '東', '東南', '南', '西南', '西', '西北', '北'];
    const idx = Math.round((deg % 360) / 45) % 8;
    return directions[idx];
  }

  // ---------------------------------------------------------------------------
  // 10. 多尺度連續潮汐波動走勢圖 (Tidal Wave Plot)
  // ---------------------------------------------------------------------------
  function drawTideWave(d) {
    const canvas = dom.canvasTideWave;
    if (!canvas || !d.tide.wave_series || d.tide.wave_series.length === 0) return;
    const ctx = canvas.getContext('2d');
    const width = (canvas.width = canvas.parentElement.clientWidth || 560);
    const height = (canvas.height = 340);

    ctx.clearRect(0, 0, width, height);

    const padL = 48;
    const padR = 24;
    const padT = 36;
    const padB = 45;
    const plotW = width - padL - padR;
    const plotH = height - padT - padB;

    const series = d.tide.wave_series;

    let minH = -2.6;
    let maxH = 3.2;
    series.forEach((pt) => {
      if (pt.height < minH) minH = Math.floor(pt.height) - 0.5;
      if (pt.height > maxH) maxH = Math.ceil(pt.height) + 0.5;
    });

    function getY(val) {
      return padT + plotH * (1.0 - (val - minH) / (maxH - minH));
    }
    function getX(idx) {
      return padL + (idx / (series.length - 1)) * plotW;
    }

    // 輔助水位格線
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
    ctx.lineWidth = 1;
    ctx.font = '10px Inter, sans-serif';
    ctx.fillStyle = '#64748b';
    ctx.textAlign = 'right';

    for (let hVal = Math.ceil(minH); hVal <= Math.floor(maxH); hVal += 1) {
      const y = getY(hVal);
      ctx.beginPath();
      ctx.moveTo(padL, y);
      ctx.lineTo(padL + plotW, y);
      ctx.stroke();
      ctx.fillText(`${hVal >= 0 ? '+' : ''}${hVal}m`, padL - 8, y + 3);
    }

    // 0m 海平面基線
    const yZero = getY(0);
    ctx.strokeStyle = 'rgba(56, 189, 248, 0.35)';
    ctx.setLineDash([4, 4]);
    ctx.beginPath();
    ctx.moveTo(padL, yZero);
    ctx.lineTo(padL + plotW, yZero);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = 'rgba(56, 189, 248, 0.6)';
    ctx.fillText('0.0m 海平面', padL + plotW, yZero - 6);

    // 平滑波浪漸變 Fill
    const waveGrad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
    waveGrad.addColorStop(0, 'rgba(14, 165, 233, 0.45)');
    waveGrad.addColorStop(1, 'rgba(2, 132, 199, 0.02)');

    ctx.beginPath();
    ctx.moveTo(getX(0), getY(series[0].height));
    for (let i = 1; i < series.length; i++) {
      ctx.lineTo(getX(i), getY(series[i].height));
    }
    ctx.lineTo(getX(series.length - 1), getY(minH));
    ctx.lineTo(getX(0), getY(minH));
    ctx.closePath();
    ctx.fillStyle = waveGrad;
    ctx.fill();

    // 波形主線
    ctx.beginPath();
    ctx.moveTo(getX(0), getY(series[0].height));
    for (let i = 1; i < series.length; i++) {
      ctx.lineTo(getX(i), getY(series[i].height));
    }
    ctx.strokeStyle = '#38bdf8';
    ctx.lineWidth = 2.2;
    ctx.stroke();

    // 滿潮/乾潮極值標註
    const showLabels = state.spanDays <= 3;
    series.forEach((pt, idx) => {
      if (pt.point_type === 'high') {
        const x = getX(idx);
        const y = getY(pt.height);
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = '#f43f5e';
        ctx.fill();
        if (showLabels) {
          ctx.font = 'bold 10px Inter, sans-serif';
          ctx.fillStyle = '#fda4af';
          ctx.textAlign = 'center';
          ctx.fillText(`${pt.time}`, x, y - 8);
        }
      } else if (pt.point_type === 'low') {
        const x = getX(idx);
        const y = getY(pt.height);
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = '#38bdf8';
        ctx.fill();
        if (showLabels) {
          ctx.font = 'bold 10px Inter, sans-serif';
          ctx.fillStyle = '#7dd3fc';
          ctx.textAlign = 'center';
          ctx.fillText(`${pt.time}`, x, y + 14);
        }
      }
    });

    // 當前時間標尺垂直線
    const currentTs = state.simulatedDate.getTime() / 1000;
    let closestIdx = 0;
    let minDiff = Infinity;
    series.forEach((pt, idx) => {
      const diff = Math.abs(pt.timestamp - currentTs);
      if (diff < minDiff) {
        minDiff = diff;
        closestIdx = idx;
      }
    });

    const curX = getX(closestIdx);
    const curY = getY(d.tide.current_height);

    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 1.8;
    ctx.beginPath();
    ctx.moveTo(curX, padT);
    ctx.lineTo(curX, padT + plotH);
    ctx.stroke();

    ctx.beginPath();
    ctx.arc(curX, curY, 6, 0, Math.PI * 2);
    ctx.fillStyle = '#f59e0b';
    ctx.fill();
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.stroke();

    ctx.font = 'bold 11px Inter, sans-serif';
    ctx.fillStyle = '#fef08a';
    ctx.textAlign = 'center';
    const sign = d.tide.current_height >= 0 ? '+' : '';
    ctx.fillText(`現在 ${sign}${d.tide.current_height.toFixed(2)}m`, curX, padT - 10);

    // 橫座標時間刻度
    ctx.textAlign = 'center';
    ctx.fillStyle = '#94a3b8';
    ctx.font = '10px Inter, sans-serif';
    const stepInterval = Math.max(1, Math.floor(series.length / 6));
    for (let i = 0; i < series.length; i += stepInterval) {
      ctx.fillText(series[i].time, getX(i), padT + plotH + 18);
    }
  }

  // 全域導出
  window.SolarTide = {
    init: init,
    refresh: fetchCalculation,
    startWeather: startWeatherLoop,
    stopWeather: stopWeatherLoop,
  };

  document.addEventListener('DOMContentLoaded', () => {
    init();
  });
})();
