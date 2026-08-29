"""MJPEG streaming and WebSocket status push."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any, Callable

from fastapi import WebSocket

logger = logging.getLogger(__name__)

BOUNDARY = b"--frame"


class ConnectionManager:
    """Tracks connected WebSocket clients and broadcasts JSON messages."""

    def __init__(self) -> None:
        self._active: list[tuple[WebSocket, str]] = []
        self._lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        client = websocket.client
        if client is None:
            host = "unknown"
        else:
            host = client.host if hasattr(client, "host") else client[0]
        async with self._lock:
            self._active.append((websocket, host))

    def disconnect(self, websocket: WebSocket) -> None:
        with contextlib.suppress(ValueError):
            for pair in self._active:
                if pair[0] is websocket:
                    self._active.remove(pair)
                    break

    async def broadcast(self, message: dict[str, Any]) -> None:
        async with self._lock:
            stale = []
            for websocket, _host in self._active:
                try:
                    await websocket.send_json(message)
                except Exception:  # noqa: BLE001 - drop dead clients
                    stale.append(websocket)
            for websocket in stale:
                self.disconnect(websocket)

    def clients(self) -> list[str]:
        return [host for _ws, host in self._active]

    @property
    def count(self) -> int:
        return len(self._active)


async def status_broadcaster(
    connections: ConnectionManager,
    status_fn: Callable[[], dict[str, Any]],
    interval: float,
) -> None:
    """Periodically broadcast the system status to all WebSocket clients."""
    while True:
        try:
            await connections.broadcast(status_fn())
        except Exception as exc:  # noqa: BLE001
            logger.warning("Status broadcast failed: %s", exc)
        await asyncio.sleep(interval)
