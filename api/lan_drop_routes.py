"""
區網快速轉檔 (LAN FastDrop) REST API 與 WebSocket 路由模組
提供設備配對、雙向傳檔、網址傳遞與實時信令廣播
"""

from fastapi import APIRouter, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, StreamingResponse
from pathlib import Path
import io

from tools.lan_drop.manager import lan_drop_manager
from tools.lan_drop.models import DeviceType, PairingRequest, SendURLRequest, SessionStatus, TerminateSessionRequest
from tools.lan_drop.security import is_private_lan_ip

router = APIRouter(prefix="/api/v1/drop", tags=["LAN FastDrop"])


@router.get("/status")
async def get_drop_status(request: Request):
    """獲取當前區網狀態與活躍配對會話"""
    client_ip = request.client.host if request.client else "127.0.0.1"
    lan_ip = lan_drop_manager.get_lan_ip()
    history = lan_drop_manager.get_history()

    # 若尚無活躍 Session 或已過期，自動生成一組
    active_session = None
    for s in lan_drop_manager._sessions.values():
        if s.status.value in {"waiting_pairing", "paired"}:
            active_session = lan_drop_manager.get_session(s.session_id)
    if active_session:
        # 檢查是否已超時過期
        if active_session.status.value == "waiting_pairing" and active_session.is_expired():
            active_session.status = SessionStatus.EXPIRED

    if not active_session or active_session.status.value in {"expired", "terminated"}:
        active_session = lan_drop_manager.create_session(port=8000)

    qr_b64 = lan_drop_manager.generate_qr_code_base64(active_session)
    remaining_sec = active_session.remaining_seconds() if active_session.status.value == "waiting_pairing" else 0

    session_data = active_session.model_dump()
    if active_session.status.value in {"expired", "terminated"}:
        session_data["pin_code"] = "------"

    return {
        "client_ip": client_ip,
        "is_private_lan": is_private_lan_ip(client_ip),
        "host_ip": lan_ip,
        "port": active_session.port,
        "session": session_data,
        "qr_code": qr_b64,
        "remaining_seconds": remaining_sec,
        "downloads_dir": history["downloads_dir"],
    }


@router.post("/session/new")
async def create_new_session():
    """重新生成一組全新的一性配對 Session 與 QR Code (120 秒有效)"""
    session = lan_drop_manager.create_session(port=8000, ttl_seconds=120)
    qr_b64 = lan_drop_manager.generate_qr_code_base64(session)
    return {
        "status": "success",
        "session": session.model_dump(),
        "qr_code": qr_b64,
        "remaining_seconds": session.remaining_seconds(),
    }


@router.post("/session/terminate")
async def terminate_drop_session(req: TerminateSessionRequest):
    """主動安全終止指定之配對會話與銷毀連線快取"""
    success = await lan_drop_manager.terminate_session(req.session_id, req.reason)
    return {
        "status": "success" if success else "failed",
        "session_id": req.session_id,
        "message": "會話已安全銷毀，臨時快取已清除" if success else "會話不存在或已銷毀",
    }


@router.post("/pair")
async def pair_mobile_device(req: PairingRequest, request: Request):
    """手機端提交配對請求"""
    client_ip = request.client.host if request.client else "127.0.0.1"
    client_ua = request.headers.get("user-agent", "Mobile Browser")

    success, message = lan_drop_manager.pair_device(
        session_id=req.session_id,
        token=req.token,
        client_ip=client_ip,
        client_ua=client_ua,
        pin_code=req.pin_code,
    )

    if not success:
        raise HTTPException(status_code=400, detail=message)

    # 廣播配對成功事件給電腦端
    await lan_drop_manager.broadcast_to_session(
        req.session_id,
        {
            "event": "device_paired",
            "device_ip": client_ip,
            "device_ua": client_ua,
            "message": "手機已成功連線！",
        },
    )

    session = lan_drop_manager.get_session(req.session_id)
    return {"status": "success", "message": message, "session": session.model_dump() if session else None}


@router.post("/upload")
async def upload_file(
    session_id: str = Form(...),
    sender_type: str = Form("mobile"),
    file: UploadFile = File(...),
):
    """
    雙向檔案/圖片上傳
    - 手機傳電腦：直接儲存至電腦 Downloads 目錄
    - 電腦傳手機：快取並廣播下載通知給手機
    """
    session = lan_drop_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=400, detail="無效的 Session ID")

    if session.status in (SessionStatus.EXPIRED, SessionStatus.TERMINATED):
        raise HTTPException(
            status_code=400,
            detail=f"會話已{('過期' if session.status == SessionStatus.EXPIRED else '終止')}，無法傳輸檔案",
        )

    content = await file.read()
    if len(content) > 500 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="單一檔案大小不能超過 500MB")

    sender = DeviceType(sender_type)

    if sender == DeviceType.MOBILE:
        # 存至電腦 Downloads
        record = lan_drop_manager.save_mobile_uploaded_file(
            file_bytes=content,
            original_filename=file.filename or "uploaded_file.bin",
            session_id=session_id,
        )
        # 通知電腦端即時更新
        await lan_drop_manager.broadcast_to_session(
            session_id,
            {
                "event": "file_received_on_desktop",
                "record": record.model_dump(),
                "message": f"收到手機傳來的新檔案: {record.filename}",
            },
        )
    else:
        # 電腦傳送至手機
        record = lan_drop_manager.prepare_desktop_file_for_mobile(
            file_bytes=content,
            original_filename=file.filename or "desktop_file.bin",
            session_id=session_id,
        )
        # 通知手機端觸發下載
        await lan_drop_manager.broadcast_to_session(
            session_id,
            {
                "event": "file_ready_for_mobile",
                "record": record.model_dump(),
                "download_url": record.download_url,
                "message": f"電腦端傳送了檔案: {record.filename}",
            },
        )

    return {"status": "success", "record": record.model_dump()}


@router.get("/download/{file_id}")
async def download_cached_file(file_id: str):
    """手機端下載電腦傳送的快取檔案"""
    file_info = lan_drop_manager.get_mobile_download(file_id)
    if not file_info:
        raise HTTPException(status_code=404, detail="找不到該下載檔案或已過期")

    filename, file_bytes, mime_type = file_info
    import urllib.parse
    encoded_filename = urllib.parse.quote(filename)

    return StreamingResponse(
        io.BytesIO(file_bytes),
        media_type=mime_type,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            "Content-Length": str(len(file_bytes)),
        },
    )


@router.post("/url/send")
async def send_url(req: SendURLRequest):
    """
    雙向網址傳遞與安全自動開啟
    """
    if req.session_id:
        session = lan_drop_manager.get_session(req.session_id)
        if session and session.status in (SessionStatus.EXPIRED, SessionStatus.TERMINATED):
            raise HTTPException(
                status_code=400,
                detail=f"會話已{('過期' if session.status == SessionStatus.EXPIRED else '終止')}，無法傳遞網址",
            )

    record = lan_drop_manager.process_url_transfer(
        url_str=req.url,
        sender_type=req.sender_type,
        auto_open=req.auto_open,
    )

    # 廣播給另一端
    target_sessions = [req.session_id] if req.session_id else list(lan_drop_manager._sessions.keys())
    for s_id in target_sessions:
        await lan_drop_manager.broadcast_to_session(
            s_id,
            {
                "event": "url_transferred",
                "record": record.model_dump(),
                "sender_type": req.sender_type.value,
            },
        )

    return {"status": "success", "record": record.model_dump()}


@router.get("/history")
async def get_history():
    """獲取傳輸歷史清單"""
    return lan_drop_manager.get_history()


# WebSocket 信令通道
@router.websocket("/ws/{session_id}")
async def drop_websocket_endpoint(websocket: WebSocket, session_id: str):
    await lan_drop_manager.register_websocket(session_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            # 支援客戶端發送 ping 保持心跳
            if data.get("action") == "ping":
                await websocket.send_json({"event": "pong", "time": data.get("time")})
    except WebSocketDisconnect:
        lan_drop_manager.unregister_websocket(session_id, websocket)
        conns = lan_drop_manager._active_connections.get(session_id, [])
        if not conns:
            sess = lan_drop_manager.get_session(session_id)
            if sess and sess.status == SessionStatus.PAIRED:
                await lan_drop_manager.terminate_session(session_id, "All devices disconnected")
    except Exception:
        lan_drop_manager.unregister_websocket(session_id, websocket)
