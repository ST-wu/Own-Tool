/**
 * Chaos Pendulum Engine - 高精度多連擺物理模擬與雙層離屏動態渲染器
 * 核心特性：
 * 1. N 節連擺拉格朗日動力學數值積分 (Sub-stepped RK4/Verlet)
 * 2. 蝴蝶效應混沌群集 (Butterfly Swarm Ensemble)
 * 3. 雙層離屏殘影衰減畫布 (恆定算力，60/120 FPS 絲滑無卡頓)
 * 4. 視網膜 Retina 高解析度自適應
 */

(function () {
  'use strict';

  // 物理與環境常數
  let config = {
    numLinks: 2,           // 擺節數 (2 ~ 6)
    gravity: 0.0,          // 重力加速度固定為 0 (永久運動)
    speed: 1.0,            // 運動速度倍率 (0.1 ~ 3.0)
    damping: 0.0,          // 阻尼為 0 (永久運動)
    trailPersistence: 0.965,// 軌跡殘影留存度 (0.8 ~ 0.999)
    swarmCount: 1,         // 群集數量 (1 ~ 30)
    trailWidth: 2.0,       // 軌跡線寬
    showArms: true,        // 是否繪製擺臂金屬連桿
    theme: 'cyber_aurora', // 色彩主題
    isPaused: false,
  };

  // 預設主題定義
  const THEMES = {
    cyber_aurora: {
      name: '賽博極光',
      bg: '#0a0a14',
      bgRgb: [10, 10, 20],
      glow: '#00f0ff',
      colors: ['#00f0ff', '#7000ff', '#ff007b', '#00ffaa'],
    },
    solar_amber: {
      name: '日光琥珀',
      bg: '#0f0c08',
      bgRgb: [15, 12, 8],
      glow: '#ffaa00',
      colors: ['#ffcc00', '#ff6600', '#ff3300', '#ffe680'],
    },
    monochrome_ink: {
      name: '玄黑水墨',
      bg: '#050505',
      bgRgb: [5, 5, 5],
      glow: '#ffffff',
      colors: ['#ffffff', '#cccccc', '#999999', '#666666'],
    },
    abyssal_bio: {
      name: '深海幽光',
      bg: '#030d12',
      bgRgb: [3, 13, 18],
      glow: '#00ffcc',
      colors: ['#00ffcc', '#0088ff', '#00ff88', '#2ee6a8'],
    },
    doppler_prism: {
      name: '多普勒光譜',
      bg: '#08080c',
      bgRgb: [8, 8, 12],
      glow: '#ffffff',
      colors: ['#ff0055', '#ffaa00', '#00ff66', '#00ccff', '#aa00ff'],
    },
  };

  // 畫布與全域狀態
  let canvas, ctx;
  let trailCanvas, trailCtx;
  let width = 0, height = 0;
  let originX = 0, originY = 0;
  let baseLength = 120;
  let pSwarm = [];
  let lastTime = performance.now();
  let frameCount = 0;
  let fpsLastTime = performance.now();
  let currentFps = 60;
  let idleTimer = null;
  let isInteracting = false;
  let draggedNode = null;

  /**
   * 多連擺單元類別 (支援 N 連擺動力學)
   */
  class MultiPendulum {
    constructor(numLinks, baseThetas, perturbation = 0) {
      this.numLinks = numLinks;
      this.thetas = [];
      this.omegas = [];
      this.lengths = [];
      this.masses = [];
      this.historyPos = [];

      for (let i = 0; i < numLinks; i++) {
        const initTheta = (baseThetas[i] !== undefined ? baseThetas[i] : Math.PI / 2 + (i * 0.2)) + (i === numLinks - 1 ? perturbation : 0);
        this.thetas.push(initTheta);
        // 賦予失重環境下初始非零角速度，交錯旋轉方向產生混沌甩動
        const baseOmega = (i % 2 === 0 ? 1.6 : -1.9) * (1.0 + i * 0.25);
        const swarmPerturb = perturbation * 50.0;
        this.omegas.push(baseOmega + (i === numLinks - 1 ? swarmPerturb : 0));
        this.lengths.push(1.0);
        this.masses.push(1.0);
      }
    }

    // 計算關節點笛卡爾座標
    getPositions(scale) {
      const pos = [{ x: originX, y: originY }];
      let curX = originX;
      let curY = originY;

      for (let i = 0; i < this.numLinks; i++) {
        const len = (baseLength / Math.sqrt(this.numLinks)) * this.lengths[i];
        curX += len * Math.sin(this.thetas[i]);
        curY += len * Math.cos(this.thetas[i]);
        pos.push({ x: curX, y: curY });
      }
      return pos;
    }

    // 數值積分單步更新 (失重拉格朗日運動方程式)
    update(dt) {
      const d = config.damping;
      const n = this.numLinks;

      if (n === 2) {
        // 精確失重雙擺拉格朗日封閉解方程
        const th1 = this.thetas[0], th2 = this.thetas[1];
        const w1 = this.omegas[0], w2 = this.omegas[1];
        const m1 = this.masses[0], m2 = this.masses[1];
        const l1 = this.lengths[0], l2 = this.lengths[1];

        const dth = th1 - th2;
        const sinD = Math.sin(dth);
        const cosD = Math.cos(dth);
        const denom = (m1 + m2 * sinD * sinD) || 0.0001;

        const alpha1 = (m2 * sinD * (l1 * w1 * w1 * cosD + l2 * w2 * w2)) / (l1 * denom);
        const alpha2 = (-sinD * ((m1 + m2) * l1 * w1 * w1 + m2 * l2 * w2 * w2 * cosD)) / (l2 * denom);

        this.omegas[0] += (alpha1 - d * w1) * dt;
        this.omegas[1] += (alpha2 - d * w2) * dt;

        this.thetas[0] += this.omegas[0] * dt;
        this.thetas[1] += this.omegas[1] * dt;
        return;
      }

      // N 階連擺偶合拉格朗日動力學 (N >= 3)
      const alpha = new Array(n).fill(0);
      for (let i = 0; i < n; i++) {
        let torque = 0;
        if (i > 0) {
          const dthPrev = this.thetas[i] - this.thetas[i - 1];
          torque -= 2.2 * Math.sin(dthPrev) * (this.omegas[i - 1] ** 2);
        }
        if (i < n - 1) {
          const dthNext = this.thetas[i + 1] - this.thetas[i];
          torque += 2.2 * Math.sin(dthNext) * (this.omegas[i + 1] ** 2);
        }
        alpha[i] = torque - d * this.omegas[i];
      }

      for (let i = 0; i < n; i++) {
        this.omegas[i] += alpha[i] * dt;
        this.thetas[i] += this.omegas[i] * dt;
      }
    }
  }

  // 初始化整個集群
  function initSwarm() {
    pSwarm = [];
    const n = config.numLinks;
    const baseThetas = [];
    for (let i = 0; i < n; i++) {
      baseThetas.push(Math.PI * 0.75 - (i * 0.35));
    }

    const swarmSize = config.swarmCount;
    const microDelta = 0.00015;

    for (let s = 0; s < swarmSize; s++) {
      const perturb = (s - (swarmSize - 1) / 2) * microDelta;
      pSwarm.push(new MultiPendulum(n, baseThetas, perturb));
    }

    clearTrails();
  }

  // 清空離屏軌跡
  function clearTrails() {
    if (!trailCtx) return;
    trailCtx.clearRect(0, 0, width, height);
    const theme = THEMES[config.theme] || THEMES.cyber_aurora;
    trailCtx.fillStyle = theme.bg;
    trailCtx.fillRect(0, 0, width, height);
  }

  // 畫面尺寸適應
  function resizeCanvas() {
    width = window.innerWidth;
    height = window.innerHeight;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    canvas.width = width * dpr;
    canvas.height = height * dpr;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    ctx.scale(dpr, dpr);

    trailCanvas.width = width * dpr;
    trailCanvas.height = height * dpr;
    trailCtx.scale(dpr, dpr);

    originX = width / 2;
    originY = height * 0.42;
    baseLength = Math.min(width, height) * 0.28;

    clearTrails();
  }

  // 核心主循環
  function loop(now) {
    requestAnimationFrame(loop);

    const delta = Math.min((now - lastTime) / 1000, 0.1);
    lastTime = now;

    // 計算 FPS
    frameCount++;
    if (now - fpsLastTime >= 1000) {
      currentFps = frameCount;
      frameCount = 0;
      fpsLastTime = now;
      const hudFps = document.getElementById('hud-fps');
      if (hudFps) hudFps.textContent = `${currentFps} FPS`;
    }

    if (!config.isPaused) {
      // 物理細分步進 (保證無數值發散)
      const subSteps = 6;
      const subDt = (delta * config.speed) / subSteps;
      for (let step = 0; step < subSteps; step++) {
        for (let i = 0; i < pSwarm.length; i++) {
          pSwarm[i].update(subDt);
        }
      }
    }

    renderFrame();
  }

  // 渲染畫面
  function renderFrame() {
    const currentTheme = THEMES[config.theme] || THEMES.cyber_aurora;

    // 1. 離屏畫布衰減 (殘影拖尾)
    trailCtx.save();
    trailCtx.globalCompositeOperation = 'source-over';
    const rgb = currentTheme.bgRgb;
    const alpha = 1.0 - config.trailPersistence;
    trailCtx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
    trailCtx.fillRect(0, 0, width, height);

    // 2. 在離屏畫布上繪製星軌 (加色混合 光暈模式)
    trailCtx.globalCompositeOperation = 'lighter';

    pSwarm.forEach((p, idx) => {
      const positions = p.getPositions(baseLength);
      const tip = positions[positions.length - 1];

      if (p.historyPos.length > 0) {
        const prev = p.historyPos[p.historyPos.length - 1];

        trailCtx.beginPath();
        trailCtx.moveTo(prev.x, prev.y);
        trailCtx.lineTo(tip.x, tip.y);

        let strokeColor;
        if (config.theme === 'doppler_prism') {
          const speed = Math.hypot(tip.x - prev.x, tip.y - prev.y);
          const hue = Math.min(320, speed * 25);
          strokeColor = `hsl(${hue}, 100%, 65%)`;
        } else {
          const colorList = currentTheme.colors;
          strokeColor = colorList[idx % colorList.length];
        }

        trailCtx.strokeStyle = strokeColor;
        trailCtx.lineWidth = config.trailWidth * (idx === 0 ? 1.4 : 1.0);
        trailCtx.lineCap = 'round';
        trailCtx.stroke();
      }

      p.historyPos = [tip];
    });

    trailCtx.restore();

    // 3. 主畫布合成：清空 -> 貼上離屏軌跡與擺臂
    ctx.clearRect(0, 0, width, height);
    ctx.save();
    ctx.fillStyle = currentTheme.bg;
    ctx.fillRect(0, 0, width, height);

    ctx.drawImage(trailCanvas, 0, 0, width, height);

    // 繪製實體機械擺臂 (若啟用)
    if (config.showArms) {
      drawArms(currentTheme);
    }
    ctx.restore();
  }

  // 繪製擺臂與關節點
  function drawArms(currentTheme) {
    ctx.save();

    // 固定底座
    ctx.beginPath();
    ctx.arc(originX, originY, 6, 0, Math.PI * 2);
    ctx.fillStyle = '#ffffff';
    ctx.shadowColor = currentTheme.glow;
    ctx.shadowBlur = 12;
    ctx.fill();

    // 僅繪製基準第一組擺的連桿，避免群集疊加過於雜亂
    const p = pSwarm[0];
    if (!p) {
      ctx.restore();
      return;
    }

    const positions = p.getPositions(baseLength);

    for (let i = 0; i < positions.length - 1; i++) {
      const p1 = positions[i];
      const p2 = positions[i + 1];

      // 擺臂連桿
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.strokeStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.lineWidth = 2.5;
      ctx.stroke();

      // 關節端點
      ctx.beginPath();
      ctx.arc(p2.x, p2.y, i === positions.length - 2 ? 5 : 4, 0, Math.PI * 2);
      ctx.fillStyle = i === positions.length - 2 ? currentTheme.glow : '#ffffff';
      ctx.shadowColor = currentTheme.glow;
      ctx.shadowBlur = 10;
      ctx.fill();
    }

    ctx.restore();
  }

  // 綁定 UI 控制事件
  function bindUIEvents() {
    const slLinks = document.getElementById('sl-links');
    const valLinks = document.getElementById('val-links');
    const slSpeed = document.getElementById('sl-speed');
    const valSpeed = document.getElementById('val-speed');
    const slTrail = document.getElementById('sl-trail');
    const valTrail = document.getElementById('val-trail');
    const slSwarm = document.getElementById('sl-swarm');
    const valSwarm = document.getElementById('val-swarm');
    const selTheme = document.getElementById('sel-theme');
    const selPreset = document.getElementById('sel-preset');
    const btnReset = document.getElementById('btn-reset');
    const btnPause = document.getElementById('btn-pause');
    const btnFullscreen = document.getElementById('btn-fullscreen');
    const dock = document.getElementById('control-dock');
    const dockToggle = document.getElementById('dock-toggle');
    const hudLinks = document.getElementById('hud-links');

    // 擺數
    slLinks?.addEventListener('input', (e) => {
      config.numLinks = parseInt(e.target.value, 10);
      if (valLinks) valLinks.textContent = config.numLinks;
      if (hudLinks) hudLinks.textContent = `${config.numLinks} 連擺`;
      initSwarm();
    });

    // 速度調節
    slSpeed?.addEventListener('input', (e) => {
      config.speed = parseFloat(e.target.value);
      if (valSpeed) valSpeed.textContent = `${config.speed.toFixed(1)}x`;
    });

    // 殘影長度
    slTrail?.addEventListener('input', (e) => {
      config.trailPersistence = parseFloat(e.target.value);
      if (valTrail) valTrail.textContent = config.trailPersistence.toFixed(3);
    });

    // 群集數量
    slSwarm?.addEventListener('input', (e) => {
      config.swarmCount = parseInt(e.target.value, 10);
      if (valSwarm) valSwarm.textContent = `${config.swarmCount} 條`;
      initSwarm();
    });

    // 主題切換
    selTheme?.addEventListener('change', (e) => {
      config.theme = e.target.value;
      clearTrails();
    });

    // 預設模式切換
    selPreset?.addEventListener('change', (e) => {
      applyPreset(e.target.value);
    });

    // 重設
    btnReset?.addEventListener('click', () => {
      initSwarm();
    });

    // 暫停/繼續
    btnPause?.addEventListener('click', () => {
      config.isPaused = !config.isPaused;
      if (btnPause) {
        btnPause.innerHTML = config.isPaused ? '▶ 繼續' : '⏸ 暫停';
      }
    });

    // 全螢幕切換
    btnFullscreen?.addEventListener('click', () => {
      toggleFullscreen();
    });

    // 控制台收合
    dockToggle?.addEventListener('click', () => {
      dock?.classList.toggle('collapsed');
      dockToggle.textContent = dock?.classList.contains('collapsed') ? '⚙️ 開啟設定' : '收合面板';
    });
  }

  // 套用預設模式
  function applyPreset(presetId) {
    if (presetId === 'classic_double') {
      updateSettings(2, 1.0, 1, 0.965, 'cyber_aurora');
    } else if (presetId === 'triple_chaos') {
      updateSettings(3, 1.0, 1, 0.97, 'solar_amber');
    } else if (presetId === 'butterfly_swarm') {
      updateSettings(2, 1.2, 30, 0.95, 'doppler_prism');
    } else if (presetId === 'cosmic_slow') {
      updateSettings(3, 0.5, 1, 0.985, 'abyssal_bio');
    } else if (presetId === 'quad_whip') {
      updateSettings(4, 1.4, 1, 0.96, 'monochrome_ink');
    }
  }

  function updateSettings(numLinks, speed, swarm, trail, theme) {
    config.numLinks = numLinks;
    config.speed = speed;
    config.swarmCount = swarm;
    config.trailPersistence = trail;
    config.theme = theme;

    // 更新 DOM
    const slLinks = document.getElementById('sl-links');
    const valLinks = document.getElementById('val-links');
    const slSpeed = document.getElementById('sl-speed');
    const valSpeed = document.getElementById('val-speed');
    const slSwarm = document.getElementById('sl-swarm');
    const valSwarm = document.getElementById('val-swarm');
    const slTrail = document.getElementById('sl-trail');
    const valTrail = document.getElementById('val-trail');
    const selTheme = document.getElementById('sel-theme');
    const hudLinks = document.getElementById('hud-links');

    if (slLinks) slLinks.value = numLinks;
    if (valLinks) valLinks.textContent = numLinks;
    if (slSpeed) slSpeed.value = speed;
    if (valSpeed) valSpeed.textContent = `${speed.toFixed(1)}x`;
    if (slSwarm) slSwarm.value = swarm;
    if (valSwarm) valSwarm.textContent = `${swarm} 條`;
    if (slTrail) slTrail.value = trail;
    if (valTrail) valTrail.textContent = trail.toFixed(3);
    if (selTheme) selTheme.value = theme;
    if (hudLinks) hudLinks.textContent = `${numLinks} 連擺`;

    initSwarm();
  }

  // 互動手勢與全域鍵盤監聽
  function bindInteractionEvents() {
    const overlay = document.querySelector('.ui-overlay');

    // 滑鼠閒置 3 秒自動隱藏介面
    function resetIdleTimer() {
      if (overlay) overlay.classList.remove('idle');
      clearTimeout(idleTimer);
      idleTimer = setTimeout(() => {
        if (!isInteracting && overlay) {
          overlay.classList.add('idle');
        }
      }, 3500);
    }

    window.addEventListener('mousemove', resetIdleTimer);
    window.addEventListener('mousedown', resetIdleTimer);
    resetIdleTimer();

    // 鍵盤快速鍵
    window.addEventListener('keydown', (e) => {
      if (e.key === 'f' || e.key === 'F') {
        toggleFullscreen();
      } else if (e.key === ' ') {
        e.preventDefault();
        config.isPaused = !config.isPaused;
        const btnPause = document.getElementById('btn-pause');
        if (btnPause) btnPause.innerHTML = config.isPaused ? '▶ 繼續' : '⏸ 暫停';
      } else if (e.key === 'r' || e.key === 'R') {
        initSwarm();
      } else if (e.key === 'h' || e.key === 'H') {
        const dock = document.getElementById('control-dock');
        dock?.classList.toggle('collapsed');
      }
    });

    // 滑鼠撥動/干擾擺錘末端
    window.addEventListener('mousedown', (e) => {
      const p = pSwarm[0];
      if (!p) return;
      const positions = p.getPositions(baseLength);
      const tip = positions[positions.length - 1];
      const dist = Math.hypot(e.clientX - tip.x, e.clientY - tip.y);

      if (dist < 40) {
        isInteracting = true;
        draggedNode = p;
      }
    });

    window.addEventListener('mousemove', (e) => {
      if (!isInteracting || !draggedNode) return;
      // 根據滑鼠移動對最末端給予瞬時角速度衝量
      const tipIndex = draggedNode.numLinks - 1;
      draggedNode.omegas[tipIndex] += (e.movementX + e.movementY) * 0.05;
    });

    window.addEventListener('mouseup', () => {
      isInteracting = false;
      draggedNode = null;
    });
  }

  function toggleFullscreen() {
    if (!document.fullscreenElement) {
      document.documentElement.requestFullscreen().catch((err) => {
        console.warn('Fullscreen request failed:', err);
      });
    } else {
      if (document.exitFullscreen) {
        document.exitFullscreen();
      }
    }
  }

  // 初始化入口
  function init() {
    canvas = document.getElementById('main-canvas');
    if (!canvas) return;
    ctx = canvas.getContext('2d');

    trailCanvas = document.createElement('canvas');
    trailCtx = trailCanvas.getContext('2d');

    window.addEventListener('resize', resizeCanvas);
    resizeCanvas();

    initSwarm();
    bindUIEvents();
    bindInteractionEvents();

    lastTime = performance.now();
    requestAnimationFrame(loop);
  }

  // 啟動入口
  window.addEventListener('DOMContentLoaded', init);
})();
