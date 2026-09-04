"""
區網快速轉檔 (LAN FastDrop) 資料模型
"""

import time
from enum import Enum
from pydantic import BaseModel, Field


class DeviceType(str, Enum):
    DESKTOP = "desktop"
    MOBILE = "mobile"


class SessionStatus(str, Enum):
    WAITING_PAIRING = "waiting_pairing"
    PAIRED = "paired"
    EXPIRED = "expired"
    TERMINATED = "terminated"


class DropSession(BaseModel):
    """配對會話資料模型"""
    session_id: str
    pin_code: str
    token: str
    created_at: float = Field(default_factory=time.time)
    expires_at: float
    status: SessionStatus = SessionStatus.WAITING_PAIRING
    host_ip: str
    port: int = 8000
    paired_device_ip: str | None = None
    paired_device_ua: str | None = None
    paired_at: float | None = None
    last_activity_at: float = Field(default_factory=time.time)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def remaining_seconds(self) -> int:
        rem = int(self.expires_at - time.time())
        return max(0, rem)


class TerminateSessionRequest(BaseModel):
    """主動終止會話請求"""
    session_id: str
    reason: str = "User closed interface or backgrounded"


class FileTransferRecord(BaseModel):
    """檔案傳輸紀錄模型"""
    id: str
    filename: str
    file_size: int
    mime_type: str = "application/octet-stream"
    sender_type: DeviceType
    receiver_type: DeviceType
    saved_path: str | None = None
    timestamp: float = Field(default_factory=time.time)
    is_image: bool = False
    download_url: str | None = None


class URLTransferRecord(BaseModel):
    """網址傳遞紀錄模型"""
    id: str
    url: str
    title: str | None = None
    sender_type: DeviceType
    is_safe: bool = True
    safety_reason: str = "通過協定與格式安全檢驗"
    auto_opened: bool = False
    timestamp: float = Field(default_factory=time.time)


class PairingRequest(BaseModel):
    """手機端配對請求"""
    session_id: str
    token: str
    pin_code: str | None = None


class SendURLRequest(BaseModel):
    """網址傳送請求"""
    url: str
    sender_type: DeviceType = DeviceType.DESKTOP
    auto_open: bool = True
    session_id: str | None = None
