import asyncio
from typing import Any
from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from core.op_logger import op_logger
from tools.smart_clipboard.manager import clipboard_manager
from tools.smart_clipboard.models import (
    ClipboardConfig,
    ClipboardMode,
    ClipboardState,
    SelectItemRequest,
    SetItemPinnedRequest,
    ToggleRequest,
    UpdateConfigRequest,
)

clipboard_router = APIRouter(prefix="/api/v1/clipboard", tags=["Smart Clipboard"])

# 活躍 WebSocket 連線池與主非同步迴圈參照
_active_ws_connections: set[WebSocket] = set()
_main_loop: asyncio.AbstractEventLoop | None = None


async def _broadcast_clipboard_event(event_data: dict[str, Any]) -> None:
    """向所有連接的 Web 客戶端廣播剪貼簿變更事件"""
    disconnected = set()
    for ws in list(_active_ws_connections):
        try:
            await ws.send_json(event_data)
        except Exception:
            disconnected.add(ws)
    _active_ws_connections.difference_update(disconnected)


def _dispatch_clipboard_event(event_data: dict[str, Any]) -> None:
    """支援跨執行緒安全派發 WebSocket 廣播通知"""
    global _main_loop
    if _main_loop and _main_loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast_clipboard_event(event_data), _main_loop)
    else:
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_broadcast_clipboard_event(event_data))
        except RuntimeError:
            try:
                asyncio.run(_broadcast_clipboard_event(event_data))
            except Exception:
                pass


# 註冊跨執行緒安全廣播鉤子
clipboard_manager.register_broadcast_hook(_dispatch_clipboard_event)


@clipboard_router.get("/state", response_model=ClipboardState)
async def get_clipboard_state():
    """獲取剪貼簿管家當前運行狀態、佇列項目與配置"""
    return clipboard_manager.get_state()


@clipboard_router.post("/toggle", response_model=ClipboardState)
async def toggle_clipboard(req: ToggleRequest):
    """
    直觀開啟或完全關閉剪貼簿管家
    - 關閉時會終止監聽線程並徹底銷毀記憶體卡片，確保零殘留
    """
    if req.enable:
        state = clipboard_manager.enable(mode=req.mode)
        op_logger.log("TOOL:CLIPBOARD_ENABLE", "INFO", details=f"啟用智慧剪貼簿管家 | 模式={state.mode.value}")
    else:
        state = clipboard_manager.disable()
        op_logger.log("TOOL:CLIPBOARD_DISABLE", "INFO", details="完全關閉智慧剪貼簿管家並銷毀清空暫存")

    await _broadcast_clipboard_event({
        "event": "state_changed",
        "state": state.model_dump(),
    })
    return state


class AdvanceRequest(BaseModel):
    step: int = 1


@clipboard_router.post("/advance")
async def advance_clipboard(req: AdvanceRequest = AdvanceRequest()):
    """
    依據當前模式推進佇列：
    - POINTER 模式：指標向前/後移動，並將目標項目寫入系統剪貼簿
    - FIFO 模式：彈出消耗隊首項目
    """
    cfg = clipboard_manager._config
    if cfg.mode == ClipboardMode.FIFO_CONSUME:
        item = clipboard_manager.consume_next_fifo()
    else:
        item = clipboard_manager.advance_pointer(step=req.step)

    if not item:
        raise HTTPException(status_code=400, detail="剪貼簿佇列為空，無可操作項目")

    state = clipboard_manager.get_state()
    await _broadcast_clipboard_event({
        "event": "item_advanced",
        "current_item": item.model_dump(),
        "state": state.model_dump(),
    })
    return {"status": "success", "item": item.model_dump(), "state": state.model_dump()}


@clipboard_router.post("/repeat")
async def repeat_current_item():
    """
    重複貼上當前項保護 (解決同一內容需貼上多次的痛點)：
    重新將當前項目內容載入系統剪貼簿，不消耗、不推進指標
    """
    item = clipboard_manager.repeat_current()
    if not item:
        raise HTTPException(status_code=400, detail="當前無選取之剪貼項目")

    return {"status": "success", "item": item.model_dump(), "message": "已重新載入當前項目至剪貼簿"}


@clipboard_router.post("/select")
async def select_clipboard_item(req: SelectItemRequest):
    """手動點選任一卡片載入系統剪貼簿"""
    item = clipboard_manager.select_item(req.item_id)
    if not item:
        raise HTTPException(status_code=404, detail="找不到指定的剪貼項目")

    state = clipboard_manager.get_state()
    await _broadcast_clipboard_event({
        "event": "item_selected",
        "selected_item": item.model_dump(),
        "state": state.model_dump(),
    })
    return {"status": "success", "item": item.model_dump(), "state": state.model_dump()}


@clipboard_router.post("/item/{item_id}/pin")
async def set_item_pinned_status(item_id: str, req: SetItemPinnedRequest):
    """釘選/鎖定項目 (防淘汰保護，便於重複重複使用)"""
    success = clipboard_manager.set_pinned(item_id, req.pinned)
    if not success:
        raise HTTPException(status_code=404, detail="找不到指定的剪貼項目")

    state = clipboard_manager.get_state()
    await _broadcast_clipboard_event({
        "event": "state_changed",
        "state": state.model_dump(),
    })
    return {"status": "success", "item_id": item_id, "is_pinned": req.pinned}


@clipboard_router.delete("/item/{item_id}")
async def remove_clipboard_item(item_id: str):
    """手動刪除單一剪貼卡片"""
    success = clipboard_manager.remove_item(item_id)
    if not success:
        raise HTTPException(status_code=404, detail="找不到指定的剪貼項目")

    state = clipboard_manager.get_state()
    await _broadcast_clipboard_event({
        "event": "state_changed",
        "state": state.model_dump(),
    })
    return {"status": "success", "message": "已移除項目"}


@clipboard_router.post("/clear")
async def clear_all_items():
    """手動清空所有剪貼卡片"""
    clipboard_manager.clear()
    state = clipboard_manager.get_state()
    op_logger.log("TOOL:CLIPBOARD_CLEAR", "INFO", details="使用者手動清空剪貼簿卡片佇列")
    await _broadcast_clipboard_event({
        "event": "state_changed",
        "state": state.model_dump(),
    })
    return {"status": "success", "state": state.model_dump()}


@clipboard_router.post("/config")
async def update_config(req: UpdateConfigRequest):
    """更新上限容量、模式或自動銷毀時間"""
    current_cfg = clipboard_manager._config.model_copy()
    if req.max_capacity is not None:
        current_cfg.max_capacity = req.max_capacity
    if req.ignore_duplicates is not None:
        current_cfg.ignore_duplicates = req.ignore_duplicates
    if req.auto_purge_minutes is not None:
        current_cfg.auto_purge_minutes = req.auto_purge_minutes
    if req.mode is not None:
        current_cfg.mode = req.mode

    clipboard_manager.set_config(current_cfg)
    state = clipboard_manager.get_state()
    await _broadcast_clipboard_event({
        "event": "state_changed",
        "state": state.model_dump(),
    })
    return {"status": "success", "config": current_cfg.model_dump(), "state": state.model_dump()}


@clipboard_router.websocket("/ws")
async def clipboard_websocket_endpoint(websocket: WebSocket):
    """剪貼簿即時雙向 WebSocket 推播頻道"""
    global _main_loop
    _main_loop = asyncio.get_running_loop()
    await websocket.accept()
    _active_ws_connections.add(websocket)
    try:
        # 連線建立後先推送一次當前狀態
        state = clipboard_manager.get_state()
        await websocket.send_json({
            "event": "init",
            "state": state.model_dump(),
        })

        while True:
            # 接收客戶端心跳或指令
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        _active_ws_connections.discard(websocket)
