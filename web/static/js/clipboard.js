/**
 * Smart Clipboard Manager (智慧剪貼簿進階管家)
 * 具備直觀啟閉開關、防爆上限、重複過濾、同內容重複貼上/游標步進，以及關閉後 100% 零殘留徹底銷毀。
 */

(function () {
  'use strict';

  let state = {
    isActive: false,
    mode: 'auto_advance',
    currentIndex: 0,
    totalItems: 0,
    items: [],
    config: {
      max_capacity: 15,
      ignore_duplicates: true,
      auto_purge_minutes: 15,
      mode: 'auto_advance',
    },
  };

  let ws = null;
  let isInitialized = false;

  const dom = {};

  function cacheDom() {
    dom.masterToggle = document.getElementById('chk-clipboard-master-toggle');
    dom.toggleLabel = document.getElementById('clipboard-toggle-label');
    dom.pulsePill = document.getElementById('clipboard-pulse-pill');
    dom.pulseText = document.getElementById('clipboard-pulse-text');
    dom.hubMetaText = document.getElementById('clipboard-hub-meta-text');
    dom.btnModeAutoAdvance = document.getElementById('btn-mode-auto-advance');
    dom.btnModeLocked = document.getElementById('btn-mode-locked');
    dom.btnClear = document.getElementById('btn-clipboard-clear');
    dom.queueHint = document.getElementById('clipboard-queue-hint');
    dom.selMaxCapacity = document.getElementById('sel-clipboard-max-capacity');
    dom.chkIgnoreDup = document.getElementById('chk-clipboard-ignore-dup');
    dom.selAutoPurge = document.getElementById('sel-clipboard-auto-purge');
    dom.counterText = document.getElementById('clipboard-counter-text');
    dom.focusBadge = document.getElementById('current-focus-badge');
    dom.focusIndex = document.getElementById('current-focus-index');
    dom.cardsGrid = document.getElementById('clipboard-cards-grid');
    dom.backToHubBtn = document.getElementById('clipboard-back-to-hub-btn');
    dom.enterClipboardBtn = document.getElementById('btn-enter-clipboard');
    dom.openCard = document.getElementById('open-tool-clipboard-card');
  }

  async function init() {
    cacheDom();
    if (!isInitialized) {
      bindEvents();
      isInitialized = true;
    }
    await fetchState();
    connectWebSocket();
  }

  function bindEvents() {
    // 總開關切換
    dom.masterToggle?.addEventListener('change', async (e) => {
      await toggleActive(e.target.checked);
    });

    // 模式切換
    dom.btnModeAutoAdvance?.addEventListener('click', () => switchMode('auto_advance'));
    dom.btnModeLocked?.addEventListener('click', () => switchMode('locked'));

    // 快捷操作 (手動清空)
    dom.btnClear?.addEventListener('click', () => clearAll());

    // 配置更新
    dom.selMaxCapacity?.addEventListener('change', (e) => {
      updateConfig({ max_capacity: parseInt(e.target.value, 10) });
    });
    dom.chkIgnoreDup?.addEventListener('change', (e) => {
      updateConfig({ ignore_duplicates: e.target.checked });
    });
    dom.selAutoPurge?.addEventListener('change', (e) => {
      updateConfig({ auto_purge_minutes: parseInt(e.target.value, 10) });
    });

    // 返回主主控台
    dom.backToHubBtn?.addEventListener('click', () => {
      if (window.AppRouter) window.AppRouter.showMainHub();
    });

    // 卡片進入
    const enterAction = () => {
      if (window.AppRouter) window.AppRouter.switchView('view-clipboard-container');
    };
    dom.enterClipboardBtn?.addEventListener('click', enterAction);
    dom.openCard?.addEventListener('click', (e) => {
      if (e.target.tagName !== 'BUTTON') enterAction();
    });
  }

  async function fetchState() {
    try {
      const res = await fetch('/api/v1/clipboard/state');
      if (!res.ok) return;
      const data = await res.json();
      state = data;
      renderState(state);
    } catch (e) {
      console.warn('Fetch clipboard state failed:', e);
    }
  }

  async function toggleActive(enable) {
    try {
      const res = await fetch('/api/v1/clipboard/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enable, mode: state.mode }),
      });
      if (!res.ok) return;
      const data = await res.json();
      state = data;
      renderState(state);
    } catch (e) {
      console.error('Toggle clipboard failed:', e);
    }
  }

  async function switchMode(newMode) {
    state.mode = newMode;
    await updateConfig({ mode: newMode });
  }

  async function advance(step = 1) {
    if (!state.isActive || state.items.length === 0) return;
    try {
      const res = await fetch('/api/v1/clipboard/advance', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ step }),
      });
      if (!res.ok) return;
      const data = await res.json();
      state = data.state;
      renderState(state);
      showToastBanner(`已載入項目至剪貼簿: ${data.item.preview}`);
    } catch (e) {
      console.error('Advance failed:', e);
    }
  }

  async function repeatCurrent() {
    if (!state.isActive || state.items.length === 0) return;
    try {
      const res = await fetch('/api/v1/clipboard/repeat', { method: 'POST' });
      if (!res.ok) return;
      const data = await res.json();
      showToastBanner(`已重新載入當前項至剪貼簿: ${data.item.preview}`);
    } catch (e) {
      console.error('Repeat failed:', e);
    }
  }

  async function selectItem(itemId) {
    try {
      const res = await fetch('/api/v1/clipboard/select', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ item_id: itemId }),
      });
      if (!res.ok) return;
      const data = await res.json();
      state = data.state;
      renderState(state);
      showToastBanner(`已手動選取載入剪貼簿: ${data.item.preview}`);
    } catch (e) {
      console.error('Select item failed:', e);
    }
  }

  async function togglePin(itemId, isPinned) {
    try {
      const res = await fetch(`/api/v1/clipboard/item/${itemId}/pin`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pinned: isPinned }),
      });
      if (!res.ok) return;
      await fetchState();
    } catch (e) {
      console.error('Toggle pin failed:', e);
    }
  }

  async function deleteItem(itemId) {
    try {
      const res = await fetch(`/api/v1/clipboard/item/${itemId}`, { method: 'DELETE' });
      if (!res.ok) return;
      await fetchState();
    } catch (e) {
      console.error('Delete item failed:', e);
    }
  }

  async function clearAll() {
    if (state.items.length > 0 && !confirm('確定要清空銷毀所有剪貼卡片嗎？')) {
      return;
    }
    try {
      const res = await fetch('/api/v1/clipboard/clear', { method: 'POST' });
      if (!res.ok) return;
      const data = await res.json();
      state = data.state;
      renderState(state);
    } catch (e) {
      console.error('Clear failed:', e);
    }
  }

  async function updateConfig(newConfig) {
    try {
      const res = await fetch('/api/v1/clipboard/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(newConfig),
      });
      if (!res.ok) return;
      const data = await res.json();
      state = data.state;
      renderState(state);
    } catch (e) {
      console.error('Update config failed:', e);
    }
  }

  function renderState(curState) {
    // 1. 總開關狀態
    const active = curState.is_active;
    if (dom.masterToggle) dom.masterToggle.checked = active;
    if (dom.toggleLabel) {
      dom.toggleLabel.textContent = active ? 'ON (監聽佇列中)' : 'OFF (已關閉銷毀)';
      dom.toggleLabel.className = `toggle-state-text ${active ? 'active' : ''}`;
    }

    if (dom.pulsePill) {
      dom.pulsePill.className = `status-pill ${active ? 'online' : 'offline'}`;
      if (dom.pulseText) {
        dom.pulseText.textContent = active ? `監聽運行中 (${curState.total_items} 項)` : '未啟用 (已清空銷毀)';
      }
    }

    if (dom.hubMetaText) {
      dom.hubMetaText.textContent = active
        ? `🟢 運行中 • ${curState.total_items} 筆暫存`
        : '⚪ 閒置已關閉 (零殘留)';
    }

    // 2. 模式按鈕狀態與提示
    const mode = curState.mode || 'auto_advance';
    const isAuto = mode === 'auto_advance' || mode === 'pointer' || mode === 'fifo_consume';
    dom.btnModeAutoAdvance?.classList.toggle('active', isAuto);
    dom.btnModeLocked?.classList.toggle('active', mode === 'locked');

    if (dom.queueHint) {
      dom.queueHint.textContent = isAuto
        ? '🟢 自動步進 (FIFO)：按 Ctrl+V 貼上後自動跳下一項'
        : '🔒 鎖定重複：當前內容已鎖定，按 Ctrl+V 可多次重複貼上';
    }

    // 3. 容量與計數器
    const maxCap = curState.config?.max_capacity || 15;
    if (dom.selMaxCapacity) dom.selMaxCapacity.value = String(maxCap);
    if (dom.chkIgnoreDup) dom.chkIgnoreDup.checked = curState.config?.ignore_duplicates ?? true;
    if (dom.selAutoPurge) dom.selAutoPurge.value = String(curState.config?.auto_purge_minutes ?? 15);

    if (dom.counterText) {
      dom.counterText.textContent = `${curState.total_items} / ${maxCap}`;
      dom.counterText.style.color = curState.total_items >= maxCap ? '#f87171' : 'var(--color-primary)';
    }

    // 4. 當前焦點卡片指標
    if (dom.focusBadge) {
      if (active && curState.items.length > 0) {
        dom.focusBadge.style.display = 'inline-flex';
        if (dom.focusIndex) {
          dom.focusIndex.textContent = `#${curState.current_index + 1}`;
        }
      } else {
        dom.focusBadge.style.display = 'none';
      }
    }

    // 5. 渲染卡片清單
    renderCards(curState);
  }

  function renderCards(curState) {
    if (!dom.cardsGrid) return;
    dom.cardsGrid.innerHTML = '';

    if (!curState.is_active || curState.items.length === 0) {
      const emptyDiv = document.createElement('div');
      emptyDiv.className = 'clipboard-empty-state';
      emptyDiv.innerHTML = `
        <div class="empty-icon-circle">📋</div>
        <h4>${curState.is_active ? '佇列目前為空' : '智慧剪貼簿處於完全關閉狀態'}</h4>
        <p>${curState.is_active
          ? '已開啟背景監聽。在任意應用中按 Ctrl+C，內容將即時捕獲並依序排列於此。'
          : '總開關關閉後，所有記憶體卡片已原子銷毀清空。開啟上方總開關即可開始使用。'
        }</p>
        <div class="empty-hint-tag">${curState.is_active ? '🛡️ 自動重複過濾與防爆上限保護中' : '✨ 100% 零磁碟殘留 • 隱私安全'}</div>
      `;
      dom.cardsGrid.appendChild(emptyDiv);
      return;
    }

    curState.items.forEach((item, idx) => {
      const isCurrentFocus = curState.is_active && idx === curState.current_index;
      const card = document.createElement('div');
      card.className = `clipboard-item-card ${isCurrentFocus ? 'focused' : ''}`;
      card.dataset.id = item.id;

      card.innerHTML = `
        <div class="item-card-header">
          <div class="item-badge-group">
            <span class="item-index-badge">#${idx + 1}</span>
            ${isCurrentFocus ? '<span class="item-status-pill current">🎯 當前待貼上 (Active)</span>' : ''}
          </div>
          <div class="item-actions-group">
            <button class="btn-item-action btn-copy" title="載入系統剪貼簿">📋</button>
            <button class="btn-item-action btn-del" title="刪除此項">✕</button>
          </div>
        </div>

        <div class="item-content-preview" title="點擊設為當前貼上項目">
          <pre>${escapeHtml(item.content)}</pre>
        </div>

        <div class="item-card-footer">
          <span class="item-meta">${item.char_count} 字 • ${item.line_count} 行</span>
          <span class="item-time">${formatTime(item.copied_at)}</span>
        </div>
      `;

      // 點選整張卡片或預覽區直接選取載入
      card.querySelector('.item-content-preview')?.addEventListener('click', () => selectItem(item.id));
      card.querySelector('.btn-copy')?.addEventListener('click', (e) => {
        e.stopPropagation();
        selectItem(item.id);
      });
      card.querySelector('.btn-del')?.addEventListener('click', (e) => {
        e.stopPropagation();
        deleteItem(item.id);
      });

      dom.cardsGrid.appendChild(card);
    });
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function formatTime(timestamp) {
    if (!timestamp) return '';
    const d = new Date(timestamp * 1000);
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}:${String(d.getSeconds()).padStart(2, '0')}`;
  }

  function showToastBanner(msg) {
    const banner = document.createElement('div');
    banner.className = 'clipboard-toast-banner';
    banner.textContent = msg;
    document.body.appendChild(banner);
    setTimeout(() => {
      banner.classList.add('hide');
      setTimeout(() => banner.remove(), 300);
    }, 2000);
  }

  function connectWebSocket() {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    ws = new WebSocket(`${protocol}//${window.location.host}/api/v1/clipboard/ws`);

    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        if (data.state) {
          state = data.state;
          renderState(state);
        }
      } catch (e) {
        console.warn('WS parse error:', e);
      }
    };

    ws.onclose = () => {
      setTimeout(connectWebSocket, 3000);
    };
  }

  window.ClipboardApp = {
    init,
    fetchState,
  };
})();
