/**
 * 區網快速轉檔 (LAN FastDrop) 電腦端核心互動邏輯
 * 支援動態配對、QR Code 生成、雙向檔案直傳至 Downloads 目錄、URL 安全傳遞與即時信令
 */

(function () {
  'use strict';

  let currentSession = null;
  let ws = null;
  let isInitialized = false;

  // DOM 元素快取
  let dom = {};

  function cacheDom() {
    dom = {
      qrImage: document.getElementById('drop-qr-img'),
      lanUrlText: document.getElementById('drop-lan-url'),
      pinCodeText: document.getElementById('drop-pin-code'),
      pinCodeBadge: document.getElementById('drop-pin-code-badge'),
      timerBadge: document.getElementById('drop-timer-badge'),
      countdownText: document.getElementById('drop-countdown-text'),
      qrExpiredOverlay: document.getElementById('drop-qr-expired-overlay'),
      btnRegenExpired: document.getElementById('btn-regen-expired'),
      statusBadge: document.getElementById('drop-status-badge'),
      statusText: document.getElementById('drop-status-text'),
      btnNewSession: document.getElementById('btn-new-drop-session'),
      downloadsPathText: document.getElementById('drop-downloads-path'),
      desktopDropZone: document.getElementById('desktop-drop-zone'),
      desktopFileInput: document.getElementById('desktop-file-input'),
      desktopProgressBox: document.getElementById('desktop-upload-progress'),
      desktopProgressFill: document.getElementById('desktop-progress-fill'),
      desktopProgressText: document.getElementById('desktop-progress-text'),
      urlInput: document.getElementById('desktop-url-input'),
      btnSendUrl: document.getElementById('btn-desktop-send-url'),
      chkAutoOpen: document.getElementById('chk-desktop-auto-open'),
      receivedFilesList: document.getElementById('drop-received-files-list'),
      urlHistoryList: document.getElementById('drop-url-history-list'),
      backToHubBtn: document.getElementById('drop-back-to-hub-btn'),
    };
  }

  let countdownInterval = null;

  async function init() {
    cacheDom();
    if (!isInitialized) {
      bindEvents();
      isInitialized = true;
    }
    await fetchDropStatus();
  }

  function bindEvents() {
    dom.btnNewSession?.addEventListener('click', () => generateNewSession());
    dom.btnRegenExpired?.addEventListener('click', () => generateNewSession());

    dom.desktopDropZone?.addEventListener('click', () => {
      dom.desktopFileInput?.click();
    });

    dom.desktopDropZone?.addEventListener('dragover', (e) => {
      e.preventDefault();
      dom.desktopDropZone.classList.add('dragover');
    });

    dom.desktopDropZone?.addEventListener('dragleave', () => {
      dom.desktopDropZone.classList.remove('dragover');
    });

    dom.desktopDropZone?.addEventListener('drop', (e) => {
      e.preventDefault();
      dom.desktopDropZone.classList.remove('dragover');
      const files = e.dataTransfer.files;
      if (files && files.length > 0) {
        handleDesktopUpload(files);
      }
    });

    dom.desktopFileInput?.addEventListener('change', (e) => {
      const files = e.target.files;
      if (files && files.length > 0) {
        handleDesktopUpload(files);
      }
      dom.desktopFileInput.value = '';
    });

    dom.btnSendUrl?.addEventListener('click', () => sendUrlToMobile());

    dom.backToHubBtn?.addEventListener('click', () => {
      terminateCurrentSession('使用者返回控制台');
      if (window.AppRouter) window.AppRouter.showMainHub();
    });

    window.addEventListener('beforeunload', () => {
      terminateCurrentSession('電腦端關閉頁面');
    });
  }

  function terminateCurrentSession(reason = 'Desktop disconnected') {
    if (!currentSession || currentSession.status === 'terminated') return;
    try {
      const payload = JSON.stringify({ session_id: currentSession.session_id, reason });
      if (navigator.sendBeacon) {
        const blob = new Blob([payload], { type: 'application/json' });
        navigator.sendBeacon('/api/v1/drop/session/terminate', blob);
      } else {
        fetch('/api/v1/drop/session/terminate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: payload,
          keepalive: true,
        });
      }
    } catch (e) {
      console.warn('Terminate session failed:', e);
    }
  }

  function startCountdown(seconds) {
    clearInterval(countdownInterval);
    if (!dom.timerBadge || !dom.countdownText) return;

    if (seconds <= 0) {
      handleSessionExpired();
      return;
    }

    dom.timerBadge.style.display = 'inline-flex';
    dom.timerBadge.classList.remove('warning', 'expired');
    if (dom.qrExpiredOverlay) dom.qrExpiredOverlay.style.display = 'none';

    let remaining = seconds;
    updateCountdownDisplay(remaining);

    countdownInterval = setInterval(() => {
      remaining -= 1;
      updateCountdownDisplay(remaining);

      if (remaining <= 30 && remaining > 0) {
        dom.timerBadge.classList.add('warning');
      }

      if (remaining <= 0) {
        clearInterval(countdownInterval);
        handleSessionExpired();
      }
    }, 1000);
  }

  function updateCountdownDisplay(sec) {
    if (!dom.countdownText) return;
    const m = String(Math.floor(sec / 60)).padStart(2, '0');
    const s = String(sec % 60).padStart(2, '0');
    dom.countdownText.textContent = `${m}:${s}`;
  }

  function handleSessionExpired() {
    clearInterval(countdownInterval);
    if (dom.timerBadge) {
      dom.timerBadge.classList.remove('warning');
      dom.timerBadge.classList.add('expired');
      if (dom.countdownText) dom.countdownText.textContent = '00:00 (已過期)';
    }

    // 主動銷毀與遮蔽舊 QR Code 與 PIN
    if (dom.qrImage) dom.qrImage.src = '';
    if (dom.qrExpiredOverlay) dom.qrExpiredOverlay.style.display = 'flex';
    if (dom.pinCodeText) dom.pinCodeText.textContent = '------';
    if (dom.lanUrlText) {
      dom.lanUrlText.textContent = '金鑰已失效，請重新生成';
      dom.lanUrlText.removeAttribute('href');
    }
    updateStatusBadge(false, '金鑰已過期失效');
  }

  async function fetchDropStatus() {
    try {
      const res = await fetch('/api/v1/drop/status');
      if (!res.ok) return;
      const data = await res.json();
      currentSession = data.session;

      renderSessionInfo(data);
      connectWebSocket(currentSession.session_id);
    } catch (e) {
      console.error('Fetch drop status failed:', e);
    }
  }

  async function generateNewSession() {
    try {
      const res = await fetch('/api/v1/drop/session/new', { method: 'POST' });
      if (!res.ok) return;
      const data = await res.json();
      currentSession = data.session;

      renderSessionInfo(data);

      if (ws) ws.close();
      connectWebSocket(currentSession.session_id);
    } catch (e) {
      console.error('Generate new session failed:', e);
    }
  }

  function renderSessionInfo(data) {
    if (dom.downloadsPathText) {
      dom.downloadsPathText.textContent = data.downloads_dir;
    }

    const session = data.session;
    const isPaired = session?.status === 'paired';
    const isWaiting = session?.status === 'waiting_pairing';

    if (isWaiting) {
      if (dom.qrImage) dom.qrImage.src = data.qr_code;
      if (dom.qrExpiredOverlay) dom.qrExpiredOverlay.style.display = 'none';
      if (dom.lanUrlText && session) {
        dom.lanUrlText.textContent = `http://${session.host_ip}:${session.port}/drop`;
        dom.lanUrlText.href = `http://${session.host_ip}:${session.port}/drop?s=${session.session_id}&t=${session.token}&pin=${session.pin_code}`;
      }
      if (dom.pinCodeText && session) {
        dom.pinCodeText.textContent = session.pin_code;
      }
      updateStatusBadge(false, '等待手機掃碼...');
      startCountdown(data.remaining_seconds || 120);
    } else if (isPaired) {
      clearInterval(countdownInterval);
      if (dom.timerBadge) dom.timerBadge.style.display = 'none';
      if (dom.qrExpiredOverlay) dom.qrExpiredOverlay.style.display = 'none';
      updateStatusBadge(true, '手機已連線');
    } else {
      handleSessionExpired();
    }
  }

  function updateStatusBadge(isPaired, text) {
    if (!dom.statusBadge || !dom.statusText) return;
    if (isPaired) {
      dom.statusBadge.className = 'drop-status-badge connected';
      dom.statusText.textContent = text || '手機已連線';
    } else {
      dom.statusBadge.className = 'drop-status-badge';
      dom.statusText.textContent = text || '等待配對';
    }
  }

  function connectWebSocket(sessionId) {
    if (!sessionId) return;
    if (ws) {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        return; // 已有有效連線，避免重複建立
      }
      try { ws.close(); } catch (e) {}
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/api/v1/drop/ws/${sessionId}`);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        handleWsEvent(data);
      } catch (e) {
        console.error('WS Parse Error:', e);
      }
    };

    ws.onclose = () => {
      setTimeout(() => {
        if (currentSession) connectWebSocket(currentSession.session_id);
      }, 3000);
    };
  }

  function handleWsEvent(data) {
    if (data.event === 'device_paired') {
      clearInterval(countdownInterval);
      if (dom.timerBadge) dom.timerBadge.style.display = 'none';
      if (dom.qrExpiredOverlay) dom.qrExpiredOverlay.style.display = 'none';
      updateStatusBadge(true, `手機已配對 (${data.device_ip})`);
    } else if (data.event === 'session_terminated') {
      clearInterval(countdownInterval);
      handleSessionExpired();
      updateStatusBadge(false, `連線已安全中斷 (${data.reason || '已斷開'})`);
    } else if (data.event === 'file_received_on_desktop') {
      addReceivedFileRecord(data.record);
    } else if (data.event === 'url_transferred') {
      addUrlTransferRecord(data.record);
    }
  }

  function addReceivedFileRecord(record) {
    if (!dom.receivedFilesList || !record || !record.id) return;
    // 嚴格 ID 去重防護
    if (document.getElementById(`file-rec-${record.id}`)) return;

    const emptyPlaceholder = dom.receivedFilesList.querySelector('.empty-state-text');
    if (emptyPlaceholder) emptyPlaceholder.remove();

    const item = document.createElement('div');
    item.id = `file-rec-${record.id}`;
    item.className = 'transfer-record-item';
    item.innerHTML = `
      <div class="record-left">
        <div class="record-icon ${record.is_image ? 'img-icon' : 'file-icon'}">
          ${record.is_image 
            ? '<svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>'
            : '<svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/></svg>'
          }
        </div>
        <div class="record-meta">
          <div class="record-name" title="${record.saved_path || record.filename}">${record.filename}</div>
          <div class="record-sub">
            <span class="badge-tag green">已存至 Downloads</span>
            <span>${formatFileSize(record.file_size)}</span>
            <span>${new Date(record.timestamp * 1000).toLocaleTimeString()}</span>
          </div>
        </div>
      </div>
      <div class="record-right">
        <span class="device-tag mobile-tag">來自手機</span>
      </div>
    `;

    dom.receivedFilesList.prepend(item);
  }

  function addUrlTransferRecord(record) {
    if (!dom.urlHistoryList || !record || !record.id) return;
    // 嚴格 ID 去重防護
    if (document.getElementById(`url-rec-${record.id}`)) return;

    const emptyPlaceholder = dom.urlHistoryList.querySelector('.empty-state-text');
    if (emptyPlaceholder) emptyPlaceholder.remove();

    const item = document.createElement('div');
    item.id = `url-rec-${record.id}`;
    item.className = 'transfer-record-item';
    item.innerHTML = `
      <div class="record-left">
        <div class="record-icon url-icon">
          <svg width="20" height="20" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"/></svg>
        </div>
        <div class="record-meta">
          <a href="${record.url}" target="_blank" rel="noopener noreferrer" class="record-name url-link">${record.url}</a>
          <div class="record-sub">
            <span class="badge-tag ${record.is_safe ? 'green' : 'red'}">${record.is_safe ? '✓ 安全驗證通過' : '✗ 危險網址攔截'}</span>
            ${record.auto_opened ? '<span class="badge-tag blue">已自動在瀏覽器開啟</span>' : ''}
            <span>${new Date(record.timestamp * 1000).toLocaleTimeString()}</span>
          </div>
        </div>
      </div>
      <div class="record-right">
        <span class="device-tag ${record.sender_type === 'mobile' ? 'mobile-tag' : 'desktop-tag'}">
          ${record.sender_type === 'mobile' ? '手機發送' : '電腦發送'}
        </span>
      </div>
    `;

    dom.urlHistoryList.prepend(item);
  }

  async function handleDesktopUpload(files) {
    if (!currentSession) return;

    for (let i = 0; i < files.length; i++) {
      await uploadDesktopFile(files[i]);
    }
  }

  async function uploadDesktopFile(file) {
    if (dom.desktopProgressBox) dom.desktopProgressBox.style.display = 'flex';
    if (dom.desktopProgressText) dom.desktopProgressText.textContent = `傳送至手機: ${file.name} (0%)`;
    if (dom.desktopProgressFill) dom.desktopProgressFill.style.width = '0%';

    const formData = new FormData();
    formData.append('session_id', currentSession.session_id);
    formData.append('sender_type', 'desktop');
    formData.append('file', file);

    return new Promise((resolve, reject) => {
      const xhr = new XMLHttpRequest();
      xhr.open('POST', '/api/v1/drop/upload', true);

      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
          const pct = Math.round((e.loaded / e.total) * 100);
          if (dom.desktopProgressFill) dom.desktopProgressFill.style.width = pct + '%';
          if (dom.desktopProgressText) dom.desktopProgressText.textContent = `傳送至手機: ${file.name} (${pct}%)`;
        }
      };

      xhr.onload = () => {
        if (xhr.status === 200) {
          if (dom.desktopProgressText) dom.desktopProgressText.textContent = `傳送完成: ${file.name}`;
          setTimeout(() => {
            if (dom.desktopProgressBox) dom.desktopProgressBox.style.display = 'none';
          }, 1500);
          resolve();
        } else {
          alert('傳送至手機失敗: ' + xhr.responseText);
          if (dom.desktopProgressBox) dom.desktopProgressBox.style.display = 'none';
          reject();
        }
      };

      xhr.onerror = () => {
        alert('網路錯誤，傳送失敗');
        if (dom.desktopProgressBox) dom.desktopProgressBox.style.display = 'none';
        reject();
      };

      xhr.send(formData);
    });
  }

  async function sendUrlToMobile() {
    const url = dom.urlInput?.value?.trim();
    if (!url) return;

    try {
      const res = await fetch('/api/v1/drop/url/send', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url,
          sender_type: 'desktop',
          auto_open: false,
        }),
      });

      const data = await res.json();
      if (data.status === 'success') {
        if (dom.urlInput) dom.urlInput.value = '';
      }
    } catch (e) {
      console.error('Send URL failed:', e);
    }
  }

  function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
  }

  window.LanDropApp = {
    init,
  };
})();
