import os
import sys
import time
from core.logger import logger

# Windows 常數
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    # 設定函式原型以防 64-bit 指標截斷
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.GetClipboardData.argtypes = [wintypes.UINT]
    user32.GetClipboardData.restype = wintypes.HANDLE
    user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    user32.SetClipboardData.restype = wintypes.HANDLE
    user32.GetClipboardSequenceNumber.argtypes = []
    user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    user32.GetAsyncKeyState.argtypes = [wintypes.INT]
    user32.GetAsyncKeyState.restype = wintypes.SHORT

    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalLock.restype = wintypes.LPVOID
    kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
    kernel32.GlobalFree.restype = wintypes.HGLOBAL


# 非 Windows 或 Mock 測試 fallback 狀態
_mock_clipboard_text = ""
_mock_sequence_number = 1


def get_clipboard_sequence() -> int:
    """獲取剪貼簿內容序號 (Windows: 每次內容變更序號遞增)"""
    if not IS_WINDOWS:
        global _mock_sequence_number
        return _mock_sequence_number
    try:
        return int(user32.GetClipboardSequenceNumber())
    except Exception as e:
        logger.debug(f"[Clipboard] 讀取 SequenceNumber 失敗: {e}")
        return 0


def get_clipboard_text() -> str:
    """從系統剪貼簿讀取 Unicode 純文字"""
    if not IS_WINDOWS:
        return _mock_clipboard_text

    # Guard clause: 重試開啟剪貼簿 (最多 3 次，防止與其他軟體短暫衝突)
    opened = False
    for _ in range(3):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.015)

    if not opened:
        return ""

    try:
        h_clip_data = user32.GetClipboardData(CF_UNICODETEXT)
        if not h_clip_data:
            return ""

        p_data = kernel32.GlobalLock(h_clip_data)
        if not p_data:
            return ""

        try:
            return ctypes.wstring_at(p_data)
        finally:
            kernel32.GlobalUnlock(h_clip_data)
    except Exception as e:
        logger.debug(f"[Clipboard] 讀取內容失敗: {e}")
        return ""
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    """將文字寫入系統剪貼簿"""
    if not IS_WINDOWS:
        global _mock_clipboard_text, _mock_sequence_number
        _mock_clipboard_text = text
        _mock_sequence_number += 1
        return True

    opened = False
    for _ in range(3):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.015)

    if not opened:
        return False

    try:
        user32.EmptyClipboard()
        if not text:
            return True

        # 編碼為 UTF-16 (含結尾 null 字元)
        encoded = (text + "\0").encode("utf-16-le")
        buffer_size = len(encoded)

        h_mem = kernel32.GlobalAlloc(GMEM_MOVEABLE, buffer_size)
        if not h_mem:
            return False

        p_mem = kernel32.GlobalLock(h_mem)
        if not p_mem:
            kernel32.GlobalFree(h_mem)
            return False

        try:
            ctypes.memmove(p_mem, encoded, buffer_size)
        finally:
            kernel32.GlobalUnlock(h_mem)

        # 傳遞成功後，Windows 系統將擁有該全域記憶體物件所有權
        res = user32.SetClipboardData(CF_UNICODETEXT, h_mem)
        return bool(res)
    except Exception as e:
        logger.warning(f"[Clipboard] 寫入內容失敗: {e}")
        return False
    finally:
        user32.CloseClipboard()


def is_paste_hotkey_pressed() -> bool:
    """檢查使用者是否在 Windows 下按下了貼上快捷鍵 (Ctrl + V)"""
    if not IS_WINDOWS:
        return False
    try:
        ctrl_down = bool(user32.GetAsyncKeyState(0x11) & 0x8000)
        v_down = bool(user32.GetAsyncKeyState(0x56) & 0x8000)
        return ctrl_down and v_down
    except Exception as e:
        logger.debug(f"[Clipboard] 偵測按鍵熱鍵失敗: {e}")
        return False
