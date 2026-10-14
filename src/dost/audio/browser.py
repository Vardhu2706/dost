"""AudioAdapter for the browser call UI (binary PCM16 over a FastAPI WebSocket)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Protocol

from fastapi import WebSocket, WebSocketDisconnect


class AudioAdapter(Protocol):
    def frames(self) -> AsyncIterator[bytes]: ...
    async def send(self, chunk: bytes) -> None: ...
    async def clear_output(self) -> None: ...
    async def close(self) -> None: ...


class BrowserWSAdapter:
    def __init__(self, ws: WebSocket, out_sample_rate: int) -> None:
        self._ws = ws
        self._out_rate = out_sample_rate
        self._closed = False

    async def start(self) -> None:
        await self._ws.send_text(json.dumps({"type": "hello", "sample_rate": self._out_rate}))

    async def frames(self) -> AsyncIterator[bytes]:
        try:
            while True:
                msg = await self._ws.receive()
                if msg["type"] == "websocket.disconnect":
                    return
                if msg.get("bytes"):
                    yield msg["bytes"]
                elif msg.get("text") == "hangup":
                    return
        except (WebSocketDisconnect, RuntimeError):
            return

    async def send(self, chunk: bytes) -> None:
        if not self._closed:
            await self._ws.send_bytes(chunk)

    async def clear_output(self) -> None:
        if not self._closed:
            await self._ws.send_text(json.dumps({"type": "clear"}))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._ws.close()
        except RuntimeError:
            pass
