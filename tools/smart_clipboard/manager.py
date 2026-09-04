import threading
import time
from typing import Any, Callable, Coroutine
from core.logger import logger
from tools.smart_clipboard.models import (
    ClipItem,
    ClipboardConfig,
    ClipboardMode,
    ClipboardState,
)
from tools.smart_clipboard.windows_clipboard import (
    get_clipboard_sequence,
    get_clipboard_text,
    is_paste_hotkey_pressed,
    set_clipboard_text,
)


class SmartClipboardManager:
    """
    智慧剪貼簿進階管家核心引擎
    管理佇列防爆上限、重複過濾、靈活貼上模式與零殘留銷毀生命週期
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._config = ClipboardConfig()
        self._items: list[ClipItem] = []
        self._current_index: int = 0
        self._is_active: bool = False
        self._last_activity_at: float = time.time()
        self._last_sequence: int = 0
        self._last_copied_text: str = ""

        # 背景監聽執行緒管控
        self._stop_event = threading.Event()
        self._worker_thread: threading.Thread | None = None
        self._broadcast_hook: Callable[[dict[str, Any]], Any] | None = None

    def register_broadcast_hook(self, hook: Callable[[dict[str, Any]], Any]) -> None:
        """註冊非同步/跨執行緒廣播通知回呼 (供 WebSocket 推播使用)"""
        self._broadcast_hook = hook

    def set_config(self, config: ClipboardConfig) -> None:
        """更新剪貼簿配置"""
        with self._lock:
            self._config = config
            self._enforce_capacity_guard()

    def get_state(self) -> ClipboardState:
        """獲取當前完整狀態與卡片清單"""
        with self._lock:
            # 檢查閒置自動銷毀
            self._check_auto_purge()
            return ClipboardState(
                is_active=self._is_active,
                mode=self._config.mode,
                current_index=self._current_index,
                total_items=len(self._items),
                items=list(self._items),
                config=self._config.model_copy(),
                last_activity_at=self._last_activity_at,
            )

    def enable(self, mode: ClipboardMode | None = None) -> ClipboardState:
        """
        直觀開啟剪貼簿管家：
        啟動背景序列監聽執行緒，進入主動接收狀態
        """
        with self._lock:
            if mode:
                self._config.mode = mode

            if not self._is_active:
                self._is_active = True
                self._last_activity_at = time.time()
                self._last_sequence = get_clipboard_sequence()
                self._last_copied_text = get_clipboard_text()

                self._stop_event.clear()
                self._worker_thread = threading.Thread(
                    target=self._monitor_clipboard_loop,
                    name="SmartClipboardWorker",
                    daemon=True,
                )
                self._worker_thread.start()
                logger.info(f"[SmartClipboard] 剪貼簿管家已啟用 | 模式={self._config.mode.value} | 上限={self._config.max_capacity}")

            return self.get_state()

    def disable(self) -> ClipboardState:
        """
        直觀關閉剪貼簿管家：
        停止背景監聽執行緒，並執行原子銷毀 (Purge) 徹底清空記憶體與暫存項目，保證 100% 零殘留
        """
        with self._lock:
            if self._is_active:
                self._is_active = False
                self._stop_event.set()
                self._worker_thread = None

                # 徹底銷毀與重置所有卡片與記錄
                self._items.clear()
                self._current_index = 0
                self._last_copied_text = ""
                logger.info("[SmartClipboard] 剪貼簿管家已完全關閉，所有暫存項目已原子銷毀清空")

            return self.get_state()

    def add_clip(self, content: str, is_pinned: bool = False) -> ClipItem | None:
        """
        新增複製項目至佇列 (套用重複過濾與防爆上限淘汰)
        """
        if not content or not content.strip():
            return None

        with self._lock:
            # 1. 重複過濾 (防止連續按 Ctrl+C 產生冗餘重複項目)
            if self._config.ignore_duplicates and self._items:
                if self._items[-1].content == content:
                    logger.debug("[SmartClipboard] 偵測到與上一筆相同之內容，已自動忽略")
                    return None

            item = ClipItem(content=content, is_pinned=is_pinned)
            self._items.append(item)
            self._last_activity_at = time.time()

            # 2. 防爆上限保護
            self._enforce_capacity_guard()

            # 3. FIFO 佇列保證：保持待貼上指標指向最早項目 (0)
            if len(self._items) == 1:
                self._current_index = 0
                self._last_copied_text = content
            else:
                # 確保系統剪貼簿維持為當前待貼上的項目 (先進先出)
                target_item = self._items[self._current_index]
                set_clipboard_text(target_item.content)
                self._last_copied_text = target_item.content
                self._last_sequence = get_clipboard_sequence()

            logger.info(f"[SmartClipboard] 捕獲新剪貼簿項目: ID={item.id} | 長度={item.char_count}字 | 預覽={item.preview}")
            return item

    def advance_pointer(self, step: int = 1) -> ClipItem | None:
        """
        指標推進 (Pointer Mode)：
        推進或後退當前選定項目，並將其自動載入系統剪貼簿以供貼上
        """
        with self._lock:
            if not self._items:
                return None

            self._last_activity_at = time.time()
            new_idx = self._current_index + step
            # 邊界防護 (可循環或鉗制)
            if 0 <= new_idx < len(self._items):
                self._current_index = new_idx
            else:
                self._current_index = 0 if step > 0 else len(self._items) - 1

            current_item = self._items[self._current_index]
            set_clipboard_text(current_item.content)
            self._last_copied_text = current_item.content
            self._last_sequence = get_clipboard_sequence()
            logger.debug(f"[SmartClipboard] 指標推進至 [{self._current_index + 1}/{len(self._items)}]: {current_item.preview}")
            return current_item

    def consume_next_fifo(self) -> ClipItem | None:
        """
        自動消耗彈出 (FIFO Consume Mode)：
        彈出隊列最前面的項目載入剪貼簿供貼上，並將其自佇列移除 (釘選項目除外)
        """
        with self._lock:
            if not self._items:
                return None

            self._last_activity_at = time.time()
            item = self._items[0]

            # 將內容載入系統剪貼簿
            set_clipboard_text(item.content)
            self._last_copied_text = item.content

            # 若未釘選，彈出消耗
            if not item.is_pinned:
                self._items.pop(0)
                logger.debug(f"[SmartClipboard] FIFO 消耗彈出項目: {item.preview} | 剩餘={len(self._items)}")
            else:
                logger.debug(f"[SmartClipboard] 項目已釘選，保留於佇列: {item.preview}")

            self._current_index = 0
            return item

    def repeat_current(self) -> ClipItem | None:
        """
        同一內容重複貼上保護 (Repeat Current Item)：
        重新將當前項目內容載入系統剪貼簿，不消耗、不移動指標
        """
        with self._lock:
            if not self._items or self._current_index >= len(self._items):
                return None

            self._last_activity_at = time.time()
            current_item = self._items[self._current_index]
            set_clipboard_text(current_item.content)
            self._last_copied_text = current_item.content
            self._last_sequence = get_clipboard_sequence()
            logger.debug(f"[SmartClipboard] 重複載入當前項目至剪貼簿: {current_item.preview}")
            return current_item

    def select_item(self, item_id: str) -> ClipItem | None:
        """
        手動點選指定卡片：
        將該卡片內容直接寫入系統剪貼簿，並將指標定位於此
        """
        with self._lock:
            for idx, item in enumerate(self._items):
                if item.id == item_id:
                    self._current_index = idx
                    self._last_activity_at = time.time()
                    set_clipboard_text(item.content)
                    self._last_copied_text = item.content
                    self._last_sequence = get_clipboard_sequence()
                    logger.info(f"[SmartClipboard] 手動選取項目 ID={item_id} 載入系統剪貼簿")
                    return item
            return None

    def set_pinned(self, item_id: str, is_pinned: bool) -> bool:
        """釘選或解鎖項目 (釘選項目享有防淘汰保護與重複使用)"""
        with self._lock:
            for item in self._items:
                if item.id == item_id:
                    item.is_pinned = is_pinned
                    self._last_activity_at = time.time()
                    return True
            return False

    def remove_item(self, item_id: str) -> bool:
        """移除單一項目"""
        with self._lock:
            for idx, item in enumerate(self._items):
                if item.id == item_id:
                    self._items.pop(idx)
                    if self._current_index >= len(self._items):
                        self._current_index = max(0, len(self._items) - 1)
                    return True
            return False

    def clear(self) -> None:
        """一鍵手動清空全部佇列"""
        with self._lock:
            self._items.clear()
            self._current_index = 0
            self._last_activity_at = time.time()
            logger.info("[SmartClipboard] 使用者手動清空所有剪貼簿佇列")

    def _enforce_capacity_guard(self) -> None:
        """防爆上限守衛：若項目超過 max_capacity，自動淘汰最舊未釘選項目"""
        while len(self._items) > self._config.max_capacity:
            # 優先尋找最舊且未釘選的項目淘汰
            unpinned_idx = next((i for i, item in enumerate(self._items) if not item.is_pinned), None)
            if unpinned_idx is not None:
                discarded = self._items.pop(unpinned_idx)
                if unpinned_idx < self._current_index:
                    self._current_index = max(0, self._current_index - 1)
                logger.debug(f"[SmartClipboard] 超過容量上限 ({self._config.max_capacity})，自動淘汰未釘選項: {discarded.preview}")
            else:
                # 若全數皆釘選，淘汰最舊的項目以保護記憶體
                discarded = self._items.pop(0)
                self._current_index = max(0, self._current_index - 1)
                logger.debug(f"[SmartClipboard] 超過容量上限，淘汰最舊項目: {discarded.preview}")

        if self._current_index >= len(self._items):
            self._current_index = max(0, len(self._items) - 1)

    def _check_auto_purge(self) -> None:
        """檢查閒置時間是否超過設定，若超時則自動銷毀"""
        if self._config.auto_purge_minutes > 0 and self._items:
            idle_seconds = time.time() - self._last_activity_at
            if idle_seconds > (self._config.auto_purge_minutes * 60):
                logger.info(f"[SmartClipboard] 剪貼簿超過 {self._config.auto_purge_minutes} 分鐘未操作，觸發安全自動銷毀清空")
                self._items.clear()
                self._current_index = 0

    def _monitor_clipboard_loop(self) -> None:
        """背景監聽輪詢迴圈：靈敏偵測系統剪貼簿變更 (Ctrl+C) 與貼上快捷鍵 (Ctrl+V 正緣觸發)"""
        v_was_pressed = False
        while not self._stop_event.is_set():
            try:
                # 1. 偵測 Ctrl+V 貼上快捷鍵 (正緣邊緣觸發 Rising-Edge：避免連按漏抓或長按連跳)
                ctrl_v_now = is_paste_hotkey_pressed()
                if ctrl_v_now:
                    if not v_was_pressed:
                        v_was_pressed = True
                        is_auto_mode = self._config.mode in (
                            ClipboardMode.AUTO_ADVANCE,
                            ClipboardMode.POINTER,
                            ClipboardMode.FIFO_CONSUME,
                        )
                        if self._is_active and is_auto_mode and len(self._items) > 0:
                            # 微延遲 25ms 讓目標應用程式先取走當前剪貼內容，隨後即時切換至下一筆
                            time.sleep(0.025)
                            if self._config.mode == ClipboardMode.FIFO_CONSUME:
                                advanced_item = self.consume_next_fifo()
                            else:
                                advanced_item = self.advance_pointer(1)

                            if advanced_item and self._broadcast_hook:
                                try:
                                    self._broadcast_hook({
                                        "event": "item_advanced",
                                        "current_item": advanced_item.model_dump(),
                                        "state": self.get_state().model_dump(),
                                    })
                                except Exception as e:
                                    logger.debug(f"[SmartClipboard] 廣播步進異常: {e}")
                else:
                    v_was_pressed = False

                # 2. 偵測系統剪貼簿內容序號變更 (Ctrl+C / 外部複製)
                current_seq = get_clipboard_sequence()
                if current_seq != self._last_sequence:
                    self._last_sequence = current_seq
                    text = get_clipboard_text()
                    if text and text != self._last_copied_text:
                        item = self.add_clip(text)
                        if item and self._broadcast_hook:
                            try:
                                self._broadcast_hook({
                                    "event": "clip_added",
                                    "item": item.model_dump(),
                                    "state": self.get_state().model_dump(),
                                })
                            except Exception as e:
                                logger.debug(f"[SmartClipboard] 廣播新增異常: {e}")
            except Exception as e:
                logger.debug(f"[SmartClipboard] 輪詢異常: {e}")

            # 輪詢間隔 25ms (40Hz)，保證極速連按 Ctrl+V 也能即時捕獲且 CPU 佔用微乎其微
            time.sleep(0.025)


# 全域單例
clipboard_manager = SmartClipboardManager()
