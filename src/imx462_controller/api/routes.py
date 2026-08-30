"""REST routes for camera control, capture, configuration, and assets."""

from __future__ import annotations

import queue
from pathlib import Path
from typing import Any

import anyio
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from starlette.responses import FileResponse, StreamingResponse

from ..camera.service import CameraManager, CameraMode
from ..config import AppConfig
from ..mqtt.client import MqttPublisher
from .streaming import BOUNDARY, ConnectionManager

router = APIRouter(prefix="/api", tags=["camera"])

_PHOTO_KINDS = {"jpg", "jpeg", "png"}

_CAMERA_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"description": "Camera not found"},
    409: {"description": "Operation rejected (camera busy or invalid state)"},
}

_ASSET_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"description": "Invalid filename"},
    404: {"description": "Asset not found"},
}


class ModeRequest(BaseModel):
    width: int
    height: int
    bit_depth: int
    framerate: int


class ControlsRequest(BaseModel):
    controls: dict[str, Any]


class FlipRequest(BaseModel):
    hflip: bool = False
    vflip: bool = False


class StreamModeRequest(BaseModel):
    mode: str


class SnapshotRequest(BaseModel):
    exposure_us: int
    gain: float = 1.0


def _manager(request: Request) -> CameraManager:
    return request.app.state.camera_manager


def _mqtt(request: Request) -> MqttPublisher:
    return request.app.state.mqtt


def _config(request: Request) -> AppConfig:
    return request.app.state.config


def _media_dir(request: Request) -> Path:
    return Path(_config(request).capture.output_dir)


@router.get("/cameras")
def list_cameras(request: Request):
    manager = _manager(request)
    config = _config(request)
    return {
        "cameras": [
            {
                "id": c.id,
                "name": c.name,
                "model": c.model,
                "modes": [m.__dict__ for m in c.modes],
                "default_mode": c.default_mode.__dict__ if c.default_mode else None,
                "capabilities": c.capabilities.to_dict() if c.capabilities else None,
            }
            for c in manager.list_cameras()
        ],
        "default_mode": config.default_mode.model_dump(),
    }


@router.get("/cameras/{camera_id}/capabilities", responses=_CAMERA_ERROR_RESPONSES)
def camera_capabilities(camera_id: int, request: Request):
    manager = _manager(request)
    try:
        capabilities = manager.capabilities(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    return capabilities.to_dict()


@router.get("/cameras/{camera_id}/status", responses=_CAMERA_ERROR_RESPONSES)
def camera_status(camera_id: int, request: Request):
    manager = _manager(request)
    try:
        worker = manager.get_worker(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    return {
        "id": worker.id,
        "name": worker.name,
        "recording": worker.recording,
        "started": worker.started,
    }


@router.get("/cameras/{camera_id}/settings", responses=_CAMERA_ERROR_RESPONSES)
def camera_settings(camera_id: int, request: Request):
    manager = _manager(request)
    try:
        worker = manager.get_worker(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    return worker.current_settings()


@router.put("/cameras/{camera_id}/mode", responses=_CAMERA_ERROR_RESPONSES)
def set_mode(camera_id: int, body: ModeRequest, request: Request):
    manager = _manager(request)
    _mqtt(request).publish_event("configure", camera_id=camera_id, mode=body.model_dump())
    try:
        manager.configure(camera_id, CameraMode(**body.model_dump()))
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "camera_id": camera_id, "mode": body.model_dump()}


@router.put("/cameras/{camera_id}/controls", responses=_CAMERA_ERROR_RESPONSES)
def set_controls(camera_id: int, body: ControlsRequest, request: Request):
    manager = _manager(request)
    try:
        manager.set_controls(camera_id, body.controls)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _mqtt(request).publish_event("controls_set", camera_id=camera_id, controls=body.controls)
    return {"ok": True, "camera_id": camera_id, "controls": body.controls}


@router.put("/cameras/{camera_id}/flip", responses=_CAMERA_ERROR_RESPONSES)
def set_flip(camera_id: int, body: FlipRequest, request: Request):
    manager = _manager(request)
    try:
        manager.set_flip(camera_id, body.hflip, body.vflip)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _mqtt(request).publish_event("flip", camera_id=camera_id, hflip=body.hflip, vflip=body.vflip)
    return {"ok": True, "camera_id": camera_id, "hflip": body.hflip, "vflip": body.vflip}


@router.put("/cameras/{camera_id}/stream-mode", responses=_CAMERA_ERROR_RESPONSES)
def set_stream_mode(camera_id: int, body: StreamModeRequest, request: Request):
    manager = _manager(request)
    try:
        manager.set_stream_mode(camera_id, body.mode)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return {"ok": True, "camera_id": camera_id, "mode": body.mode}


@router.post("/cameras/{camera_id}/snapshot", responses=_CAMERA_ERROR_RESPONSES)
def capture_snapshot(camera_id: int, body: SnapshotRequest, request: Request):
    manager = _manager(request)
    try:
        path = manager.capture_snapshot(camera_id, body.exposure_us, body.gain)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _mqtt(request).publish_event("snapshot_captured", camera_id=camera_id, path=str(path))
    return {
        "ok": True,
        "camera_id": camera_id,
        "path": str(path),
        "url": f"/api/assets/{path.name}",
    }


@router.post("/cameras/{camera_id}/photo", responses=_CAMERA_ERROR_RESPONSES)
def capture_photo(camera_id: int, request: Request):
    manager = _manager(request)
    try:
        path = manager.capture_photo(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _mqtt(request).publish_event("photo_captured", camera_id=camera_id, path=str(path))
    return {
        "ok": True,
        "camera_id": camera_id,
        "path": str(path),
        "url": f"/api/assets/{path.name}",
    }


@router.post("/cameras/{camera_id}/recording/start", responses=_CAMERA_ERROR_RESPONSES)
def start_recording(camera_id: int, request: Request):
    manager = _manager(request)
    try:
        manager.start_recording(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    _mqtt(request).publish_event("recording_started", camera_id=camera_id)
    return {"ok": True, "camera_id": camera_id, "recording": True}


@router.post("/cameras/{camera_id}/recording/stop", responses=_CAMERA_ERROR_RESPONSES)
def stop_recording(camera_id: int, request: Request):
    manager = _manager(request)
    try:
        path = manager.stop_recording(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")
    _mqtt(request).publish_event("recording_stopped", camera_id=camera_id, path=str(path))
    return {
        "ok": True,
        "camera_id": camera_id,
        "recording": False,
        "path": str(path) if path else None,
        "url": f"/api/assets/{path.name}" if path else None,
    }


@router.get("/cameras/{camera_id}/stream", responses=_CAMERA_ERROR_RESPONSES)
async def stream(camera_id: int, request: Request):
    manager = _manager(request)
    try:
        worker = manager.get_worker(camera_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Camera {camera_id} not found")

    q = worker.subscribe()

    async def _frames():
        try:
            while True:
                try:
                    frame = await anyio.to_thread.run_sync(q.get, True, 1.0)
                except queue.Empty:
                    continue
                yield BOUNDARY + b"\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
        finally:
            worker.unsubscribe(q)

    return StreamingResponse(_frames(), media_type="multipart/x-mixed-replace; boundary=frame")


@router.get("/assets")
def list_assets(request: Request):
    media_dir = _media_dir(request)
    if not media_dir.is_dir():
        return {"assets": []}
    assets = []
    for path in media_dir.iterdir():
        if not path.is_file():
            continue
        stat = path.stat()
        assets.append(
            {
                "filename": path.name,
                "kind": "photo" if path.suffix.lstrip(".").lower() in _PHOTO_KINDS else "video",
                "size": stat.st_size,
                "modified": stat.st_mtime,
            }
        )
    assets.sort(key=lambda a: a["modified"], reverse=True)
    return {"assets": assets}


def _resolve_asset(request: Request, filename: str) -> Path:
    media_dir = _media_dir(request).resolve()
    name = Path(filename).name
    if name != filename or not name:
        raise HTTPException(status_code=400, detail="Invalid filename")
    path = (media_dir / name).resolve()
    if path.parent != media_dir or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    return path


@router.get("/assets/{filename}", responses=_ASSET_ERROR_RESPONSES)
def download_asset(filename: str, request: Request):
    path = _resolve_asset(request, filename)
    media_type = (
        "image/jpeg"
        if path.suffix.lstrip(".").lower() in _PHOTO_KINDS
        else "application/octet-stream"
    )
    return FileResponse(
        path,
        media_type=media_type,
        filename=path.name,
        content_disposition_type="attachment",
    )


@router.delete("/assets/{filename}", responses=_ASSET_ERROR_RESPONSES)
def delete_asset(filename: str, request: Request):
    path = _resolve_asset(request, filename)
    path.unlink()
    _mqtt(request).publish_event("asset_deleted", filename=path.name)
    return {"ok": True, "filename": path.name}


@router.get("/config")
def get_config(request: Request):
    config = _config(request)
    return {
        "server": config.server.model_dump(),
        "cameras": [c.model_dump() for c in config.cameras],
        "default_mode": config.default_mode.model_dump(),
        "capture": config.capture.model_dump(),
        "mqtt_topics": config.mqtt.topics.model_dump(),
        "otel_service_name": config.otel.service_name,
    }


@router.websocket("/ws")
async def websocket_status(websocket: WebSocket):
    connections: ConnectionManager = websocket.app.state.connections
    manager: CameraManager = websocket.app.state.camera_manager
    await connections.connect(websocket)
    try:
        await websocket.send_json({**manager.status(), "clients": connections.clients()})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        connections.disconnect(websocket)
