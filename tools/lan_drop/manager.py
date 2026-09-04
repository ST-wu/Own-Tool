"""
區網快速轉檔 (LAN FastDrop) 管理與排程引擎
處理 Session 生命週期、本機 LAN IP 探測、QR Code 生成、雙向檔案直傳儲存至 Downloads、URL 安全檢驗與自動開啟
"""

import io
import mimetypes
import os
import secrets
import socket
import time
import uuid
import webbrowser
from pathlib import Path
from typing import Any

import qrcode
from fastapi import WebSocket
from core.logger import logger
from tools.lan_drop.models import (
    DeviceType,
    DropSession,
    FileTransferRecord,
    SessionStatus,
    URLTransferRecord,
)
from tools.lan_drop.security import (
    generate_secure_pin,
    generate_session_token,
    is_private_lan_ip,
    sanitize_filename,
    validate_url_safety,
    verify_session_token,
)


class LanDropManager:
    """區網快速轉檔 (LAN FastDrop) 核心管理器"""

    def __init__(self, downloads_dir: Path | None = None) -> None:
        self.secret_key = secrets.token_hex(32)
        self.downloads_dir = downloads_dir or (Path.home() / "Downloads")
        try:
            self.downloads_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            self.downloads_dir = Path("./downloads")
            self.downloads_dir.mkdir(parents=True, exist_ok=True)

        self._sessions: dict[str, DropSession] = {}
        self._temp_mobile_downloads: dict[str, tuple[str, bytes, str]] = {}  # {file_id: (filename, bytes, mime)}
        self._file_records: list[FileTransferRecord] = []
        self._url_records: list[URLTransferRecord] = []
        self._active_connections: dict[str, list[WebSocket]] = {}  # {session_id: [websockets]}

    def get_lan_ip(self) -> str:
        """探測本機於區域網路中的主要 IPv4 位址"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    def create_session(self, port: int = 8000, ttl_seconds: int = 120) -> DropSession:
        """建立全新的一次性配對 Session (預設 120 秒 / 2 分鐘有效)"""
        session_id = str(uuid.uuid4())
        pin_code = generate_secure_pin()
        token = generate_session_token(session_id, pin_code, self.secret_key)
        host_ip = self.get_lan_ip()

        session = DropSession(
            session_id=session_id,
            pin_code=pin_code,
            token=token,
            created_at=time.time(),
            expires_at=time.time() + ttl_seconds,
            status=SessionStatus.WAITING_PAIRING,
            host_ip=host_ip,
            port=port,
            last_activity_at=time.time(),
        )

        self._sessions[session_id] = session
        logger.info(f"[LAN FastDrop] 建立新 Session [{session_id[:8]}], PIN: {pin_code}, IP: {host_ip}:{port}, TTL: {ttl_seconds}s")
        return session

    def get_session(self, session_id: str) -> DropSession | None:
        """取得 Session 並檢查過期狀態與閒置狀態"""
        session = self._sessions.get(session_id)
        if not session:
            return None

        # 1. 待配對超時檢查 (120 秒未掃碼配對即過期)
        if session.status == SessionStatus.WAITING_PAIRING and session.is_expired():
            session.status = SessionStatus.EXPIRED

        # 2. 已配對閒置檢查 (超過 120 秒雙向無傳輸動作即主動終止防護)
        elif session.status == SessionStatus.PAIRED and (time.time() - session.last_activity_at > 120):
            session.status = SessionStatus.TERMINATED
            logger.info(f"[LAN FastDrop] 會話 [{session_id[:8]}] 因閒置逾時自動安全終止")

        return session

    def touch_activity(self, session_id: str) -> None:
        """更新會話最新活躍時間戳"""
        session = self._sessions.get(session_id)
        if session:
            session.last_activity_at = time.time()

    async def terminate_session(self, session_id: str, reason: str = "Client disconnected") -> bool:
        """主動終止會話、回收快取資源並廣播斷開信號"""
        session = self._sessions.get(session_id)
        if not session:
            return False

        session.status = SessionStatus.TERMINATED
        logger.info(f"[LAN FastDrop] 主動安全終止 Session [{session_id[:8]}], 原因: {reason}")

        # 廣播終止事件
        await self.broadcast_to_session(
            session_id,
            {
                "event": "session_terminated",
                "session_id": session_id,
                "reason": reason,
            },
        )

        # 關閉並清理 WebSocket 連線
        conns = self._active_connections.pop(session_id, [])
        for ws in conns:
            try:
                await ws.close(code=1000, reason=reason)
            except Exception:
                pass

        # 清除所有暫存快取檔案
        self._temp_mobile_downloads.clear()
        return True

    def generate_qr_code_base64(self, session: DropSession) -> str:
        """生成手機掃碼連線專用的高解析度 QR Code (Base64 Data URL)"""
        # Guard clause: 若會話已過期或已終止，嚴禁生成 QR Code
        if session.status != SessionStatus.WAITING_PAIRING or session.is_expired():
            return ""

        mobile_url = f"http://{session.host_ip}:{session.port}/drop?s={session.session_id}&t={session.token}&pin={session.pin_code}"

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=2,
        )
        qr.add_data(mobile_url)
        qr.make(fit=True)

        img = qr.make_image(fill_color="#0066ff", back_color="#ffffff")
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)
        import base64
        b64_str = base64.b64encode(buffer.getvalue()).decode("utf-8")
        return f"data:image/png;base64,{b64_str}"

    def pair_device(
        self,
        session_id: str,
        token: str,
        client_ip: str,
        client_ua: str = "Unknown Mobile",
        pin_code: str | None = None,
    ) -> tuple[bool, str]:
        """驗證手機配對請求"""
        if not is_private_lan_ip(client_ip):
            logger.warning(f"[LAN FastDrop] 拒絕非內網 IP 配對請求: {client_ip}")
            return False, "基於安全考量，僅允許同區域網路內設備連線"

        session = self.get_session(session_id)
        if not session:
            return False, "無效或不存在的配對會話"

        if session.status == SessionStatus.EXPIRED:
            return False, "此配對會話已過期，請於電腦端重新生成 QR Code"

        if session.status == SessionStatus.TERMINATED:
            return False, "此配對會話已被電腦端主動終止"

        # 驗證 Token 或 PIN
        token_valid = verify_session_token(session_id, session.pin_code, token, self.secret_key)
        pin_valid = (pin_code == session.pin_code)

        if not (token_valid or pin_valid):
            logger.warning(f"[LAN FastDrop] 配對金鑰驗證失敗 (IP: {client_ip})")
            return False, "配對憑證驗證失敗，請重新掃碼"

        session.status = SessionStatus.PAIRED
        session.paired_device_ip = client_ip
        session.paired_device_ua = client_ua
        session.paired_at = time.time()

        logger.info(f"[LAN FastDrop] 手機成功配對! (IP: {client_ip}, UA: {client_ua})")
        return True, "配對成功"

    def save_mobile_uploaded_file(
        self,
        file_bytes: bytes,
        original_filename: str,
        session_id: str,
    ) -> FileTransferRecord:
        """
        處理手機傳送至電腦之檔案
        直接且安全地儲存至電腦系統 Downloads 目錄
        """
        safe_name = sanitize_filename(original_filename)
        dest_path = self.downloads_dir / safe_name

        # 避免重名覆蓋
        counter = 1
        stem = dest_path.stem
        suffix = dest_path.suffix
        while dest_path.exists():
            dest_path = self.downloads_dir / f"{stem} ({counter}){suffix}"
            counter += 1

        dest_path.write_bytes(file_bytes)
        self.touch_activity(session_id)
        logger.info(f"[LAN FastDrop] 成功接收手機檔案並存至: {dest_path.resolve()} ({len(file_bytes)} bytes)")

        mime_type, _ = mimetypes.guess_type(dest_path.name)
        mime_type = mime_type or "application/octet-stream"
        is_img = mime_type.startswith("image/")

        record = FileTransferRecord(
            id=str(uuid.uuid4()),
            filename=dest_path.name,
            file_size=len(file_bytes),
            mime_type=mime_type,
            sender_type=DeviceType.MOBILE,
            receiver_type=DeviceType.DESKTOP,
            saved_path=str(dest_path.resolve()),
            timestamp=time.time(),
            is_image=is_img,
        )

        self._file_records.insert(0, record)
        return record

    def prepare_desktop_file_for_mobile(
        self,
        file_bytes: bytes,
        original_filename: str,
        session_id: str,
    ) -> FileTransferRecord:
        """
        處理電腦傳送至手機之檔案
        快取檔案提供手機端下載
        """
        safe_name = sanitize_filename(original_filename)
        file_id = str(uuid.uuid4())
        mime_type, _ = mimetypes.guess_type(safe_name)
        mime_type = mime_type or "application/octet-stream"
        is_img = mime_type.startswith("image/")

        self._temp_mobile_downloads[file_id] = (safe_name, file_bytes, mime_type)
        self.touch_activity(session_id)

        download_url = f"/api/v1/drop/download/{file_id}?s={session_id}"

        record = FileTransferRecord(
            id=file_id,
            filename=safe_name,
            file_size=len(file_bytes),
            mime_type=mime_type,
            sender_type=DeviceType.DESKTOP,
            receiver_type=DeviceType.MOBILE,
            saved_path=None,
            timestamp=time.time(),
            is_image=is_img,
            download_url=download_url,
        )

        self._file_records.insert(0, record)
        logger.info(f"[LAN FastDrop] 電腦端準備傳送檔案至手機: {safe_name} (ID: {file_id})")
        return record

    def get_mobile_download(self, file_id: str) -> tuple[str, bytes, str] | None:
        """取得供手機下載之快取檔案"""
        return self._temp_mobile_downloads.get(file_id)

    def process_url_transfer(
        self,
        url_str: str,
        sender_type: DeviceType,
        auto_open: bool = True,
        session_id: str | None = None,
    ) -> URLTransferRecord:
        """
        處理雙向網址傳遞與安全自動開啟
        """
        if session_id:
            self.touch_activity(session_id)

        is_safe, reason = validate_url_safety(url_str)
        auto_opened = False

        if is_safe and sender_type == DeviceType.MOBILE and auto_open:
            try:
                webbrowser.open(url_str.strip())
                auto_opened = True
                logger.info(f"[LAN FastDrop] 安全驗證通過，已自動於電腦瀏覽器開啟網址: {url_str}")
            except Exception as e:
                logger.warning(f"[LAN FastDrop] 電腦端自動開啟網址失敗: {type(e).__name__}: {e}")

        record = URLTransferRecord(
            id=str(uuid.uuid4()),
            url=url_str.strip(),
            sender_type=sender_type,
            is_safe=is_safe,
            safety_reason=reason,
            auto_opened=auto_opened,
            timestamp=time.time(),
        )

        self._url_records.insert(0, record)
        return record

    # WebSocket 廣播機制
    async def register_websocket(self, session_id: str, ws: WebSocket) -> None:
        await ws.accept()
        if session_id not in self._active_connections:
            self._active_connections[session_id] = []
        self._active_connections[session_id].append(ws)

    def unregister_websocket(self, session_id: str, ws: WebSocket) -> None:
        if session_id in self._active_connections:
            if ws in self._active_connections[session_id]:
                self._active_connections[session_id].remove(ws)

    async def broadcast_to_session(self, session_id: str, message: dict) -> None:
        conns = self._active_connections.get(session_id, [])
        dead_conns = []
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:
                dead_conns.append(ws)
        for dead in dead_conns:
            conns.remove(dead)

    def get_history(self) -> dict[str, Any]:
        """取得傳輸歷史清單"""
        return {
            "files": [r.model_dump() for r in self._file_records[:50]],
            "urls": [r.model_dump() for r in self._url_records[:50]],
            "downloads_dir": str(self.downloads_dir.resolve()),
        }


# 全域單例
lan_drop_manager = LanDropManager()
