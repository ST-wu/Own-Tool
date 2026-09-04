import time
import uuid
from enum import Enum
from pydantic import BaseModel, Field


class ClipboardMode(str, Enum):
    AUTO_ADVANCE = "auto_advance"  # 🟢 自動步進模式 (FIFO：貼上後自動跳下一項)
    LOCKED = "locked"              # 🔒 鎖定重複模式 (貼上不跳項，支援同內容重複貼上)
    POINTER = "pointer"            # 相容性別名
    FIFO_CONSUME = "fifo_consume"  # 相容性別名
    STASH = "stash"                # 相容性別名


class ClipItem(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:8])
    content: str
    char_count: int = 0
    line_count: int = 1
    is_pinned: bool = False      # 鎖定標記 (內部相容保護)
    copied_at: float = Field(default_factory=time.time)
    preview: str = ""

    def __init__(self, **data):
        super().__init__(**data)
        if self.content:
            self.char_count = len(self.content)
            self.line_count = len(self.content.splitlines()) or 1
            # 取前 60 字元做預覽
            clean_lines = " ".join(self.content.split())
            self.preview = clean_lines[:60] + ("..." if len(clean_lines) > 60 else "")


class ClipboardConfig(BaseModel):
    max_capacity: int = Field(15, ge=3, le=50, description="佇列容量上限 (防止無限累積)")
    ignore_duplicates: bool = Field(True, description="是否自動忽略連續重複複製")
    auto_purge_minutes: int = Field(15, ge=0, le=120, description="無操作自動銷毀清空時間 (分，0表示不自動銷毀)")
    mode: ClipboardMode = Field(ClipboardMode.AUTO_ADVANCE, description="運作模式")


class ClipboardState(BaseModel):
    is_active: bool = False
    mode: ClipboardMode = ClipboardMode.AUTO_ADVANCE
    current_index: int = 0
    total_items: int = 0
    items: list[ClipItem] = Field(default_factory=list)
    config: ClipboardConfig = Field(default_factory=ClipboardConfig)
    last_activity_at: float = Field(default_factory=time.time)


class ToggleRequest(BaseModel):
    enable: bool = Field(..., description="開啟 (True) 或完全關閉銷毀 (False)")
    mode: ClipboardMode | None = None


class SetItemPinnedRequest(BaseModel):
    pinned: bool = Field(..., description="是否釘選此項目以供重複貼上")


class SelectItemRequest(BaseModel):
    item_id: str = Field(..., description="選取要載入剪貼簿的項目 ID")


class UpdateConfigRequest(BaseModel):
    max_capacity: int | None = Field(None, ge=3, le=50)
    ignore_duplicates: bool | None = None
    auto_purge_minutes: int | None = Field(None, ge=0, le=120)
    mode: ClipboardMode | None = None
