"""
區網快速轉檔 (LAN FastDrop) 單元測試套件
驗證 100% 局域網安全性過濾、Session 憑證生命週期、雙向檔案直傳與 URL 安全沙盒
"""

import io
import pytest
from httpx import ASGITransport, AsyncClient
from main import app
from tools.lan_drop.manager import LanDropManager
from tools.lan_drop.models import DeviceType, SessionStatus
from tools.lan_drop.security import (
    is_private_lan_ip,
    sanitize_filename,
    validate_url_safety,
)


def test_security_ip_filter():
    """驗證私有區網 IP 白名單過濾 (RFC 1918 / Loopback)"""
    # 允許的內網 IP
    assert is_private_lan_ip("127.0.0.1") is True
    assert is_private_lan_ip("192.168.1.100") is True
    assert is_private_lan_ip("10.0.0.5") is True
    assert is_private_lan_ip("172.20.10.2") is True
    assert is_private_lan_ip("localhost") is True

    # 拒絕的外網公網 IP
    assert is_private_lan_ip("8.8.8.8") is False
    assert is_private_lan_ip("1.1.1.1") is False
    assert is_private_lan_ip("104.244.42.1") is False


def test_security_sanitize_filename():
    """驗證檔名路徑穿越消毒與危險副檔名隔離"""
    # 路徑穿越防護
    assert sanitize_filename("../../secret.txt") == "secret.txt"
    assert sanitize_filename("..\\..\\boot.ini") == "boot.ini"
    assert sanitize_filename("folder/sub/photo.png") == "photo.png"

    # 危險可執行檔隔離
    assert sanitize_filename("trojan.exe") == "trojan.exe.safe_file"
    assert sanitize_filename("hack.bat") == "hack.bat.safe_file"
    assert sanitize_filename("script.ps1") == "script.ps1.safe_file"

    # 正常檔名保留
    assert sanitize_filename("image.jpg") == "image.jpg"
    assert sanitize_filename("document.pdf") == "document.pdf"


def test_security_validate_url_safety():
    """驗證網址安全協定與 SSRF 敏感連接埠防護"""
    # 合法安全網址
    ok1, _ = validate_url_safety("https://github.com/ST-wu/Own-Tool")
    assert ok1 is True

    ok2, _ = validate_url_safety("http://192.168.1.105:8000/docs")
    assert ok2 is True

    # 危險協定阻擋
    bad1, reason1 = validate_url_safety("file:///C:/Windows/System32/cmd.exe")
    assert bad1 is False
    assert "不支援或危險的協定" in reason1

    bad2, _ = validate_url_safety("javascript:alert(document.cookie)")
    assert bad2 is False

    bad3, _ = validate_url_safety("data:text/html,<script>alert(1)</script>")
    assert bad3 is False

    # SSRF 敏感連接埠阻擋
    bad_port, reason_port = validate_url_safety("http://127.0.0.1:22/ssh")
    assert bad_port is False
    assert "敏感服務之連接埠" in reason_port


def test_session_lifecycle_and_pairing(tmp_path):
    """驗證 Session 生成、配對與過期邏輯"""
    manager = LanDropManager(downloads_dir=tmp_path)
    session = manager.create_session(ttl_seconds=300)

    assert session.status == SessionStatus.WAITING_PAIRING
    assert len(session.pin_code) == 6

    # 1. 成功配對
    success, msg = manager.pair_device(
        session_id=session.session_id,
        token=session.token,
        client_ip="192.168.1.120",
        client_ua="Mozilla/5.0 (iPhone)",
    )
    assert success is True
    assert session.status == SessionStatus.PAIRED
    assert session.paired_device_ip == "192.168.1.120"

    # 2. 測試外網 IP 拒絕
    session2 = manager.create_session(ttl_seconds=300)
    failed_ip, _ = manager.pair_device(
        session_id=session2.session_id,
        token=session2.token,
        client_ip="8.8.8.8",
    )
    assert failed_ip is False

    # 3. 測試錯誤 Token 拒絕
    session3 = manager.create_session(ttl_seconds=300)
    failed_token, _ = manager.pair_device(
        session_id=session3.session_id,
        token="invalid_token_123",
        client_ip="192.168.1.120",
    )
    assert failed_token is False


def test_file_transfers_bidirectional(tmp_path):
    """驗證雙向檔案直傳與自動存至 Downloads"""
    manager = LanDropManager(downloads_dir=tmp_path)
    session = manager.create_session(ttl_seconds=300)

    # 1. 手機傳電腦 (直接寫入 tmp_path / Downloads)
    content = b"Hello from Mobile phone photo content"
    record = manager.save_mobile_uploaded_file(
        file_bytes=content,
        original_filename="vacation.png",
        session_id=session.session_id,
    )

    assert record.sender_type == DeviceType.MOBILE
    assert record.is_image is True
    saved_file = tmp_path / "vacation.png"
    assert saved_file.exists()
    assert saved_file.read_bytes() == content

    # 2. 電腦傳手機 (快取供手機下載)
    desktop_content = b"PDF Report from Desktop"
    desktop_record = manager.prepare_desktop_file_for_mobile(
        file_bytes=desktop_content,
        original_filename="report.pdf",
        session_id=session.session_id,
    )

    assert desktop_record.sender_type == DeviceType.DESKTOP
    assert desktop_record.download_url is not None
    file_info = manager.get_mobile_download(desktop_record.id)
    assert file_info is not None
    assert file_info[0] == "report.pdf"
    assert file_info[1] == desktop_content


@pytest.mark.asyncio
async def test_lan_drop_api_routes(tmp_path):
    """驗證 LAN FastDrop 所有 REST 端點"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. 取得狀態與 QR Code
        status_res = await client.get("/api/v1/drop/status")
        assert status_res.status_code == 200
        data = status_res.json()
        assert "session" in data
        assert "qr_code" in data
        assert data["qr_code"].startswith("data:image/png;base64,")

        session_id = data["session"]["session_id"]
        token = data["session"]["token"]

        # 2. 手機端配對
        pair_res = await client.post(
            "/api/v1/drop/pair",
            json={"session_id": session_id, "token": token},
        )
        assert pair_res.status_code == 200
        pair_data = pair_res.json()
        assert pair_data["status"] == "success"

        # 3. 手機上傳檔案至電腦
        fake_file = io.BytesIO(b"Test upload payload")
        upload_res = await client.post(
            "/api/v1/drop/upload",
            data={"session_id": session_id, "sender_type": "mobile"},
            files={"file": ("test_pic.jpg", fake_file, "image/jpeg")},
        )
        assert upload_res.status_code == 200
        upload_data = upload_res.json()
        assert upload_data["status"] == "success"
        assert upload_data["record"]["filename"].startswith("test_pic")

        # 4. 發送網址
        url_res = await client.post(
            "/api/v1/drop/url/send",
            json={
                "url": "https://playwright.dev",
                "sender_type": "desktop",
                "auto_open": False,
            },
        )
        assert url_res.status_code == 200
        url_data = url_res.json()
        assert url_data["status"] == "success"
        assert url_data["record"]["is_safe"] is True

        # 5. 手機端專屬介面
        drop_html_res = await client.get("/drop")
        assert drop_html_res.status_code == 200
        assert "區網快速轉檔" in drop_html_res.text


@pytest.mark.asyncio
async def test_session_expiration_and_qr_hiding(tmp_path):
    """驗證 QR Code 逾時後主動失效、隱藏與拒絕配對"""
    manager = LanDropManager(downloads_dir=tmp_path)
    # 建立 1 秒極短時效 Session
    session = manager.create_session(ttl_seconds=1)
    assert session.remaining_seconds() <= 1
    assert session.status == SessionStatus.WAITING_PAIRING

    import asyncio
    await asyncio.sleep(1.1)

    # 1. 驗證會話判定已過期
    assert session.is_expired() is True
    retrieved = manager.get_session(session.session_id)
    assert retrieved.status == SessionStatus.EXPIRED

    # 2. 驗證已過期會話不再產生 QR Code
    qr_code = manager.generate_qr_code_base64(session)
    assert qr_code == ""

    # 3. 驗證過期會話配對遭拒
    ok, msg = manager.pair_device(
        session_id=session.session_id,
        token=session.token,
        client_ip="192.168.1.100",
    )
    assert ok is False
    assert "已過期" in msg


@pytest.mark.asyncio
async def test_session_termination_and_active_teardown(tmp_path):
    """驗證主動終止會話、回收快取與 API 熔斷端點"""
    manager = LanDropManager(downloads_dir=tmp_path)
    session = manager.create_session(ttl_seconds=120)

    # 準備電腦傳送檔案快取
    record = manager.prepare_desktop_file_for_mobile(
        file_bytes=b"Sensitive report",
        original_filename="secret.pdf",
        session_id=session.session_id,
    )
    assert manager.get_mobile_download(record.id) is not None

    # 觸發主動終止
    terminated = await manager.terminate_session(session.session_id, reason="User pressed Home button")
    assert terminated is True
    assert session.status == SessionStatus.TERMINATED

    # 驗證快取已被安全清空
    assert manager.get_mobile_download(record.id) is None

    # 透過 API 呼叫 terminate 端點
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        status_res = await client.get("/api/v1/drop/status")
        assert status_res.status_code == 200
        new_sid = status_res.json()["session"]["session_id"]

        term_res = await client.post(
            "/api/v1/drop/session/terminate",
            json={"session_id": new_sid, "reason": "Background defense triggered"},
        )
        assert term_res.status_code == 200
        assert term_res.json()["status"] == "success"

