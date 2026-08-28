/**
 * Playwright Automation Daemon - Web Console Application
 * 支援 WebSocket 即時日誌串流、動態任務表單自省、系統探活監控
 */

(function () {
  'use strict';

  // 全域狀態管理
  const state = {
    apiKey: localStorage.getItem('playwright_api_key') || 'change-me-to-a-secure-secret-key',
    activeFilter: 'ALL',
    autoScroll: true,
    tasks: [],
    currentTask: null,
    logCount: 0,
    ws: null,
    reconnectTimer: null,
  };

  // DOM 元素快取
  const elements = {
    apiKeyInput: document.getElementById('api-key-input'),
    toggleKeyVisibility: document.getElementById('toggle-key-visibility'),
    refreshBtn: document.getElementById('refresh-btn'),
    statusBadge: document.getElementById('service-status-badge'),
    statusText: document.getElementById('service-status-text'),
    latencyBadge: document.getElementById('latency-badge'),
    metricBrowser: document.getElementById('metric-browser-status'),
    metricBrowserSub: document.getElementById('metric-browser-sub'),
    metricLatency: document.getElementById('metric-latency'),
    metricTaskCount: document.getElementById('metric-task-count'),
    tasksContainer: document.getElementById('tasks-container'),
    reloadTasksBtn: document.getElementById('reload-tasks-btn'),
    wsIndicator: document.getElementById('ws-indicator'),
    wsStatusText: document.getElementById('ws-status-text'),
    terminalBody: document.getElementById('terminal-body'),
    logCountText: document.getElementById('log-count-text'),
    autoscrollChk: document.getElementById('autoscroll-chk'),
    clearLogsBtn: document.getElementById('clear-logs-btn'),
    viewConfigBtn: document.getElementById('view-config-btn'),
    taskModal: document.getElementById('task-modal'),
    modalTaskName: document.getElementById('modal-task-name'),
    modalTaskDesc: document.getElementById('modal-task-desc'),
    closeModalBtn: document.getElementById('close-modal-btn'),
    modalCancelBtn: document.getElementById('modal-cancel-btn'),
    modalSubmitBtn: document.getElementById('modal-submit-btn'),
    dynamicFormFields: document.getElementById('dynamic-form-fields'),
    taskResultBox: document.getElementById('task-result-box'),
    resultStatusBadge: document.getElementById('result-status-badge'),
    resultTime: document.getElementById('result-time'),
    resultJsonOutput: document.getElementById('result-json-output'),
    resultScreenshotWrapper: document.getElementById('result-screenshot-wrapper'),
    resultScreenshotImg: document.getElementById('result-screenshot-img'),
    configModal: document.getElementById('config-modal'),
    closeConfigModalBtn: document.getElementById('close-config-modal-btn'),
    configModalCloseBtn: document.getElementById('config-modal-close-btn'),
    configJsonOutput: document.getElementById('config-json-output'),
  };

  /* ==========================================================================
     初始化與事件綁定
     ========================================================================== */
  function init() {
    // 綁定 API Key
    elements.apiKeyInput.value = state.apiKey;
    elements.apiKeyInput.addEventListener('input', (e) => {
      state.apiKey = e.target.value.trim();
      localStorage.setItem('playwright_api_key', state.apiKey);
    });

    elements.toggleKeyVisibility.addEventListener('click', () => {
      const type = elements.apiKeyInput.type === 'password' ? 'text' : 'password';
      elements.apiKeyInput.type = type;
    });

    // 重新整理
    elements.refreshBtn.addEventListener('click', () => {
      fetchHealth();
      fetchTasks();
    });

    elements.reloadTasksBtn.addEventListener('click', fetchTasks);

    // 終端機日誌控制
    elements.autoscrollChk.addEventListener('change', (e) => {
      state.autoScroll = e.target.checked;
    });

    elements.clearLogsBtn.addEventListener('click', () => {
      elements.terminalBody.innerHTML = '<div class="terminal-line system-line">[日誌已清空] 等待新事件...</div>';
      state.logCount = 0;
      updateLogCountText();
    });

    // 日誌過濾器
    document.querySelectorAll('.filter-chips .chip').forEach((chip) => {
      chip.addEventListener('click', (e) => {
        document.querySelectorAll('.filter-chips .chip').forEach((c) => c.classList.remove('active'));
        e.target.classList.add('active');
        state.activeFilter = e.target.dataset.filter;
        applyLogFilter();
      });
    });

    // Modal 關閉
    elements.closeModalBtn.addEventListener('click', closeTaskModal);
    elements.modalCancelBtn.addEventListener('click', closeTaskModal);
    elements.modalSubmitBtn.addEventListener('click', submitTaskExecution);

    elements.viewConfigBtn.addEventListener('click', openConfigModal);
    elements.closeConfigModalBtn.addEventListener('click', closeConfigModal);
    elements.configModalCloseBtn.addEventListener('click', closeConfigModal);

    // 點擊背景關閉 Modal
    window.addEventListener('click', (e) => {
      if (e.target === elements.taskModal) closeTaskModal();
      if (e.target === elements.configModal) closeConfigModal();
    });

    // 啟動首次檢查與 WebSocket 連線 (不再於背景盲目高頻輪詢)
    fetchHealth();
    fetchTasks();
    initWebSocket();
  }

  /* ==========================================================================
     系統健康探活 (Health Polling)
     ========================================================================== */
  async function fetchHealth() {
    try {
      const res = await fetch('/health');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();

      const isHealthy = data.status === 'healthy' || data.status === 'operational';
      elements.statusBadge.className = `status-badge ${isHealthy ? 'status-operational' : 'status-degraded'}`;
      elements.statusText.textContent = isHealthy ? '系統正常運作' : '狀態異常';

      const latency = data.latency_ms !== null ? `${data.latency_ms} ms` : '-- ms';
      elements.latencyBadge.textContent = latency;
      elements.metricLatency.textContent = latency;

      elements.metricBrowser.textContent = data.browser_connected ? '連線就緒' : '未連線';
      elements.metricBrowserSub.textContent = `可用沙盒槽: ${data.available_permits || 0}`;
    } catch (err) {
      elements.statusBadge.className = 'status-badge status-degraded';
      elements.statusText.textContent = '無法連線服務';
      elements.metricBrowser.textContent = '斷線';
    }
  }

  /* ==========================================================================
     任務插件載入 (Task Hub)
     ========================================================================== */
  async function fetchTasks() {
    elements.tasksContainer.innerHTML = '<div class="tasks-loading">正在掃描任務插件...</div>';
    try {
      const res = await fetch('/api/v1/tasks', {
        headers: { 'X-API-Key': state.apiKey },
      });

      if (res.status === 401) {
        elements.tasksContainer.innerHTML = `
          <div class="clean-slate-card" style="border-color: rgba(244,63,94,0.3)">
            <div class="clean-slate-icon" style="background:rgba(244,63,94,0.15);color:var(--accent-rose)">✕</div>
            <div class="clean-slate-title">API Key 鑑權未通過 (401)</div>
            <p class="clean-slate-desc">請在右上角輸入正確的 X-API-Key 鑑權密鑰後點擊重新整理。</p>
          </div>`;
        return;
      }

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const tasks = await res.json();
      state.tasks = tasks;
      elements.metricTaskCount.textContent = tasks.length;
      renderTasks(tasks);
    } catch (err) {
      elements.tasksContainer.innerHTML = `<div class="tasks-loading">載入任務失敗: ${err.message}</div>`;
    }
  }

  function renderTasks(tasks) {
    if (!tasks || tasks.length === 0) {
      elements.tasksContainer.innerHTML = `
        <div class="clean-slate-card">
          <div class="clean-slate-icon">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 2v20M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"></path>
            </svg>
          </div>
          <div class="clean-slate-title">目前為純淨待擴充狀態</div>
          <p class="clean-slate-desc">
            預設示範任務已清空。您可以隨時在下方目錄建立繼承自 <code>BaseTask</code> 的新功能模組，系統啟動時會自動掛載於此！
          </p>
          <span class="clean-slate-path">📁 tasks/builtin/my_task.py</span>
        </div>`;
      return;
    }

    elements.tasksContainer.innerHTML = '';
    tasks.forEach((taskObj) => {
      const meta = taskObj.metadata;
      const card = document.createElement('div');
      card.className = 'task-card';

      const tagsHtml = (meta.tags || [])
        .map((tag) => `<span class="tag-badge">#${tag}</span>`)
        .join('');

      card.innerHTML = `
        <div class="task-card-header">
          <div class="task-name-badge">
            <span class="task-name">${meta.name}</span>
            <span class="task-version">v${meta.version}</span>
          </div>
          <span class="status-badge ${meta.enabled ? 'status-operational' : 'status-degraded'} btn-sm">
            ${meta.enabled ? '已啟用' : '已停用'}
          </span>
        </div>
        <p class="task-desc">${meta.description || '無詳細描述'}</p>
        <div class="task-meta-tags">${tagsHtml}</div>
        <div class="task-card-actions">
          <button class="btn btn-sm btn-ghost toggle-status-btn" data-task="${meta.name}" data-enabled="${meta.enabled}">
            ${meta.enabled ? '停用' : '啟用'}
          </button>
          <button class="btn btn-sm btn-primary run-task-btn" data-task="${meta.name}" ${!meta.enabled ? 'disabled' : ''}>
            執行此任務
          </button>
        </div>
      `;

      elements.tasksContainer.appendChild(card);
    });

    // 綁定卡片按鈕事件
    document.querySelectorAll('.run-task-btn').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        const taskName = e.currentTarget.dataset.task;
        openTaskModal(taskName);
      });
    });

    document.querySelectorAll('.toggle-status-btn').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const taskName = e.currentTarget.dataset.task;
        const currentEnabled = e.currentTarget.dataset.enabled === 'true';
        await toggleTaskStatus(taskName, !currentEnabled);
      });
    });
  }

  async function toggleTaskStatus(taskName, newStatus) {
    try {
      const res = await fetch(`/api/v1/tasks/${taskName}/status`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': state.apiKey,
        },
        body: JSON.stringify({ enabled: newStatus }),
      });
      if (res.ok) {
        fetchTasks();
      }
    } catch (e) {
      alert(`切換狀態失敗: ${e.message}`);
    }
  }

  /* ==========================================================================
     任務動態表單與執行 Modal
     ========================================================================== */
  function openTaskModal(taskName) {
    const taskObj = state.tasks.find((t) => t.metadata.name === taskName);
    if (!taskObj) return;

    state.currentTask = taskObj;
    elements.modalTaskName.textContent = `執行: ${taskObj.metadata.name}`;
    elements.modalTaskDesc.textContent = taskObj.metadata.description || '請填入執行參數';

    // 依據 JSON Schema 動態生成表單欄位
    elements.dynamicFormFields.innerHTML = '';
    const schema = taskObj.input_schema || {};
    const props = schema.properties || {};

    if (Object.keys(props).length === 0) {
      elements.dynamicFormFields.innerHTML = '<p class="text-muted" style="font-size:0.875rem">此任務無需額外輸入參數，點擊下方按鈕即可直接執行。</p>';
    } else {
      for (const [key, field] of Object.entries(props)) {
        const group = document.createElement('div');
        group.className = 'form-group';

        const label = document.createElement('label');
        label.className = 'form-label';
        label.textContent = `${field.title || key} (${field.type || 'any'})`;

        let input;
        if (field.type === 'boolean') {
          input = document.createElement('select');
          input.className = 'form-input';
          input.name = key;
          input.innerHTML = `<option value="true" ${field.default === true ? 'selected' : ''}>True</option><option value="false" ${field.default === false ? 'selected' : ''}>False</option>`;
        } else {
          input = document.createElement('input');
          input.className = 'form-input';
          input.name = key;
          input.type = field.type === 'integer' || field.type === 'number' ? 'number' : 'text';
          if (field.default !== undefined) input.value = field.default;
          if (field.description) input.placeholder = field.description;
        }

        group.appendChild(label);
        group.appendChild(input);
        if (field.description) {
          const help = document.createElement('span');
          help.className = 'form-help';
          help.textContent = field.description;
          group.appendChild(help);
        }
        elements.dynamicFormFields.appendChild(group);
      }
    }

    elements.taskResultBox.classList.add('hidden');
    elements.resultScreenshotWrapper.classList.add('hidden');
    elements.taskModal.classList.add('open');
  }

  function closeTaskModal() {
    elements.taskModal.classList.remove('open');
    state.currentTask = null;
  }

  async function submitTaskExecution() {
    if (!state.currentTask) return;
    const taskName = state.currentTask.metadata.name;

    // 收集表單參數
    const form = document.getElementById('task-dynamic-form');
    const formData = new FormData(form);
    const params = {};

    const schema = state.currentTask.input_schema || {};
    const props = schema.properties || {};

    for (const [k, v] of formData.entries()) {
      const field = props[k] || {};
      if (field.type === 'boolean') {
        params[k] = v === 'true';
      } else if (field.type === 'integer' || field.type === 'number') {
        params[k] = Number(v);
      } else {
        params[k] = v;
      }
    }

    elements.modalSubmitBtn.disabled = true;
    elements.modalSubmitBtn.querySelector('.btn-text').textContent = '執行中...';

    try {
      const res = await fetch(`/api/v1/tasks/${taskName}/run`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-API-Key': state.apiKey,
        },
        body: JSON.stringify({ params }),
      });

      const resultData = await res.json();
      renderExecutionResult(resultData);
    } catch (e) {
      renderExecutionResult({ success: false, error: e.message, execution_time_ms: 0 });
    } finally {
      elements.modalSubmitBtn.disabled = false;
      elements.modalSubmitBtn.querySelector('.btn-text').textContent = '立即執行任務';
    }
  }

  function renderExecutionResult(result) {
    elements.taskResultBox.classList.remove('hidden');

    elements.resultStatusBadge.className = `badge ${result.success ? 'status-operational' : 'status-degraded'}`;
    elements.resultStatusBadge.textContent = result.success ? '執行成功' : '執行失敗';
    elements.resultTime.textContent = `耗時: ${result.execution_time_ms} ms`;

    elements.resultJsonOutput.textContent = JSON.stringify(result, null, 2);

    // 若有截圖快照
    const screenshot = result.failure_artifact_path || (result.data && result.data.screenshot_path);
    if (screenshot) {
      // 轉換相對路徑為 /artifacts
      const cleanPath = screenshot.replace(/\\/g, '/');
      const staticUrl = '/' + cleanPath.substring(cleanPath.indexOf('artifacts'));
      elements.resultScreenshotImg.src = staticUrl;
      elements.resultScreenshotWrapper.classList.remove('hidden');
    } else {
      elements.resultScreenshotWrapper.classList.add('hidden');
    }
  }

  /* ==========================================================================
     WebSocket 即時日誌串流 (Realtime Terminal)
     ========================================================================== */
  function initWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${location.host}/ws/logs`;

    elements.wsIndicator.className = 'ws-badge ws-connecting';
    elements.wsStatusText.textContent = 'WS 連線中...';

    try {
      state.ws = new WebSocket(wsUrl);

      state.ws.onopen = () => {
        elements.wsIndicator.className = 'ws-badge ws-connected';
        elements.wsStatusText.textContent = 'WS 連線中';
      };

      state.ws.onmessage = (event) => {
        appendLogLine(event.data);
      };

      state.ws.onclose = () => {
        elements.wsIndicator.className = 'ws-badge ws-connecting';
        elements.wsStatusText.textContent = '連線中斷，重試中';
        scheduleReconnect();
      };

      state.ws.onerror = () => {
        state.ws.close();
      };
    } catch (e) {
      scheduleReconnect();
    }
  }

  function scheduleReconnect() {
    if (state.reconnectTimer) return;
    state.reconnectTimer = setTimeout(() => {
      state.reconnectTimer = null;
      initWebSocket();
    }, 3000);
  }

  function appendLogLine(rawLine) {
    if (!rawLine || !rawLine.trim()) return;

    state.logCount++;
    updateLogCountText();

    const lineDiv = document.createElement('div');
    lineDiv.className = 'terminal-line';

    // 標註層級樣式
    if (rawLine.includes('[SUCCESS]')) {
      lineDiv.classList.add('success-line');
      lineDiv.dataset.level = 'SUCCESS';
    } else if (rawLine.includes('[ERROR]')) {
      lineDiv.classList.add('error-line');
      lineDiv.dataset.level = 'ERROR';
    } else if (rawLine.includes('[WARNING]')) {
      lineDiv.classList.add('warning-line');
      lineDiv.dataset.level = 'WARNING';
    } else if (rawLine.includes('[DEBUG]')) {
      lineDiv.classList.add('debug-line');
      lineDiv.dataset.level = 'DEBUG';
    } else {
      lineDiv.classList.add('info-line');
      lineDiv.dataset.level = 'INFO';
    }

    lineDiv.textContent = rawLine;

    // 檢查當前過濾器
    if (state.activeFilter !== 'ALL' && lineDiv.dataset.level !== state.activeFilter) {
      lineDiv.style.display = 'none';
    }

    elements.terminalBody.appendChild(lineDiv);

    // 最大保留 1000 行
    if (elements.terminalBody.childElementCount > 1000) {
      elements.terminalBody.removeChild(elements.terminalBody.firstChild);
    }

    if (state.autoScroll) {
      elements.terminalBody.scrollTop = elements.terminalBody.scrollHeight;
    }
  }

  function applyLogFilter() {
    const lines = elements.terminalBody.querySelectorAll('.terminal-line');
    lines.forEach((line) => {
      if (state.activeFilter === 'ALL' || line.dataset.level === state.activeFilter || line.classList.contains('system-line')) {
        line.style.display = 'block';
      } else {
        line.style.display = 'none';
      }
    });
  }

  function updateLogCountText() {
    elements.logCountText.textContent = `顯示 ${state.logCount} 筆紀錄`;
  }

  /* ==========================================================================
     all_log_config.js 檢視 Modal
     ========================================================================== */
  async function openConfigModal() {
    try {
      const res = await fetch('/api/v1/config/logs');
      const data = await res.json();
      elements.configJsonOutput.textContent = data.raw_config || JSON.stringify(data.parsed_settings, null, 2);
      elements.configModal.classList.add('open');
    } catch (e) {
      alert(`載入設定失敗: ${e.message}`);
    }
  }

  function closeConfigModal() {
    elements.configModal.classList.remove('open');
  }

  // 頁面載入後啟動
  document.addEventListener('DOMContentLoaded', init);
})();
