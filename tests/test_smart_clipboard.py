import pytest
from httpx import ASGITransport, AsyncClient
from main import app
from tools.smart_clipboard.manager import SmartClipboardManager
from tools.smart_clipboard.models import ClipItem, ClipboardConfig, ClipboardMode


def test_clip_item_initialization():
    """驗證 ClipItem 字數、行數與預覽自動生成"""
    item = ClipItem(content="第一行內容\n第二行測試範例\n第三行結束")
    assert item.char_count == len("第一行內容\n第二行測試範例\n第三行結束")
    assert item.line_count == 3
    assert "第一行內容" in item.preview
    assert item.is_pinned is False


def test_capacity_guard_and_bounded_memory():
    """驗證防爆上限：超過容量自動淘汰最舊未釘選項目"""
    mgr = SmartClipboardManager()
    mgr.set_config(ClipboardConfig(max_capacity=3, ignore_duplicates=False))

    mgr.add_clip("Item 1")
    mgr.add_clip("Item 2")
    mgr.add_clip("Item 3")
    assert len(mgr._items) == 3

    # 加入第 4 筆，應淘汰最舊的 Item 1
    mgr.add_clip("Item 4")
    assert len(mgr._items) == 3
    contents = [i.content for i in mgr._items]
    assert "Item 1" not in contents
    assert contents == ["Item 2", "Item 3", "Item 4"]


def test_ignore_duplicates():
    """驗證連續重複內容自動過濾"""
    mgr = SmartClipboardManager()
    mgr.set_config(ClipboardConfig(max_capacity=10, ignore_duplicates=True))

    item1 = mgr.add_clip("Duplicate Text")
    assert item1 is not None

    # 連續複製相同內容，應被忽略
    item2 = mgr.add_clip("Duplicate Text")
    assert item2 is None
    assert len(mgr._items) == 1

    # 複製不同內容，應正常收錄
    item3 = mgr.add_clip("Different Text")
    assert item3 is not None
    assert len(mgr._items) == 2


def test_pinned_protection_from_capacity_discard():
    """驗證釘選保護：被鎖定項目享有防淘汰特權"""
    mgr = SmartClipboardManager()
    mgr.set_config(ClipboardConfig(max_capacity=3, ignore_duplicates=False))

    item1 = mgr.add_clip("Important Pin")
    mgr.set_pinned(item1.id, True)

    mgr.add_clip("Normal 1")
    mgr.add_clip("Normal 2")
    assert len(mgr._items) == 3

    # 加入第四筆，Normal 1 應被淘汰，Important Pin 必須被完整保留
    mgr.add_clip("Normal 3")
    assert len(mgr._items) == 3
    contents = [i.content for i in mgr._items]
    assert "Important Pin" in contents
    assert "Normal 1" not in contents
    assert "Normal 2" in contents
    assert "Normal 3" in contents


def test_pointer_mode_and_repeat_same_content():
    """驗證指標模式與同一內容重複貼上 (Repeat Current)"""
    mgr = SmartClipboardManager()
    mgr.set_config(ClipboardConfig(mode=ClipboardMode.POINTER, ignore_duplicates=False))

    mgr.add_clip("Apple")
    mgr.add_clip("Banana")
    mgr.add_clip("Cherry")

    # FIFO 順序：最先加入的 Apple 為當前預設
    first = mgr.advance_pointer(step=0)
    assert first.content == "Apple"

    # 重複載入當前項多次 (不推進、不彈出)
    rep1 = mgr.repeat_current()
    rep2 = mgr.repeat_current()
    assert rep1.content == "Apple"
    assert rep2.content == "Apple"
    assert len(mgr._items) == 3  # 項目完整保留未被消耗

    # 手動推進至下一項 Banana
    next_item = mgr.advance_pointer(step=1)
    assert next_item.content == "Banana"


def test_fifo_advance_ordering_and_system_clipboard():
    """驗證先進先出 (FIFO) 佇列與系統剪貼簿維持在首項"""
    mgr = SmartClipboardManager()
    mgr.set_config(ClipboardConfig(mode=ClipboardMode.AUTO_ADVANCE, ignore_duplicates=False))

    mgr.add_clip("First Item")
    mgr.add_clip("Second Item")
    mgr.add_clip("Third Item")

    # 驗證先進先出：最先複製的 First Item 為當前待貼上項目
    assert mgr._current_index == 0
    assert mgr._items[mgr._current_index].content == "First Item"

    # 模擬貼上後自動步進
    item1 = mgr.advance_pointer(1)
    assert item1.content == "Second Item"
    assert mgr._current_index == 1

    item2 = mgr.advance_pointer(1)
    assert item2.content == "Third Item"
    assert mgr._current_index == 2


def test_fifo_consume_mode():
    """驗證 FIFO 自動消耗模式 (彈出隊列最前項)"""
    mgr = SmartClipboardManager()
    mgr.set_config(ClipboardConfig(mode=ClipboardMode.FIFO_CONSUME, ignore_duplicates=False))

    mgr.add_clip("First")
    mgr.add_clip("Second")

    c1 = mgr.consume_next_fifo()
    assert c1.content == "First"
    assert len(mgr._items) == 1
    assert mgr._items[0].content == "Second"


def test_zero_waste_teardown_upon_disable():
    """驗證關閉時觸發原子銷毀 (Purge)：線程停止且記憶體 100% 清空零殘留"""
    mgr = SmartClipboardManager()
    mgr.enable()
    mgr.add_clip("Secret Password 123")
    mgr.add_clip("Confidential Token")
    assert len(mgr._items) == 2
    assert mgr._is_active is True

    # 執行關閉
    state = mgr.disable()
    assert state.is_active is False
    assert state.total_items == 0
    assert len(mgr._items) == 0
    assert mgr._worker_thread is None


@pytest.mark.asyncio
async def test_clipboard_api_routes():
    """驗證剪貼簿管家 FastAPI 完整端點調用"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 獲取初始狀態
        state_res = await client.get("/api/v1/clipboard/state")
        assert state_res.status_code == 200
        assert "is_active" in state_res.json()

        # 2. 開啟剪貼簿
        toggle_on = await client.post("/api/v1/clipboard/toggle", json={"enable": True})
        assert toggle_on.status_code == 200
        assert toggle_on.json()["is_active"] is True

        # 3. 更新配置
        cfg_res = await client.post("/api/v1/clipboard/config", json={"max_capacity": 10, "mode": "pointer"})
        assert cfg_res.status_code == 200
        assert cfg_res.json()["config"]["max_capacity"] == 10

        # 4. 手動清空
        clear_res = await client.post("/api/v1/clipboard/clear")
        assert clear_res.status_code == 200
        assert clear_res.json()["state"]["total_items"] == 0

        # 5. 關閉剪貼簿 (確保原子銷毀)
        toggle_off = await client.post("/api/v1/clipboard/toggle", json={"enable": False})
        assert toggle_off.status_code == 200
        assert toggle_off.json()["is_active"] is False
        assert toggle_off.json()["total_items"] == 0


def test_capacity_guard_current_index_shift():
    """驗證當容量已滿淘汰舊項目時，當前焦點指標不發生偏移"""
    mgr = SmartClipboardManager()
    mgr.set_config(ClipboardConfig(max_capacity=3, ignore_duplicates=False))

    mgr.add_clip("A")
    mgr.add_clip("B")
    mgr.add_clip("C")
    # 推進指標至 B (index 1)
    mgr.advance_pointer(1)
    assert mgr._current_index == 1
    assert mgr._items[mgr._current_index].content == "B"

    # 新增 D，導致 A 被淘汰 (A 原在 index 0)
    mgr.add_clip("D")
    assert len(mgr._items) == 3
    # 淘汰 A 後，B 應由 index 1 移至 index 0，指標需同步更新為 0
    assert mgr._current_index == 0
    assert mgr._items[mgr._current_index].content == "B"


def test_thread_safe_broadcast_dispatch():
    """驗證跨執行緒安全派發廣播不會拋出異常"""
    from api.clipboard_routes import _dispatch_clipboard_event
    # 即使在無事件迴圈之執行緒中調用亦不應崩潰
    _dispatch_clipboard_event({"event": "test_event", "data": "ping"})
