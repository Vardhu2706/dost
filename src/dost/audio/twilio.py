"""Twilio Media Streams adapter (phone leg) plus webhook helpers.

Wire format: JSON events; `media` carries base64 mu-law 8 kHz mono in 20 ms frames. Inbound is
converted to PCM16 16 kHz, outbound from the TTS PCM16 24 kHz, so nothing upstream changes.
The raw caller number is hashed at the webhook and never reaches the media socket or the DB.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from xml.sax.saxutils import quoteattr

from fastapi import WebSocket, WebSocketDisconnect

from dost.memory.models import hash_number
from dost.audio.pcm import Downsample3x, Upsample2x, mulaw_to_pcm16, pcm16_to_mulaw

OUT_CHUNK = 160  # bytes of mu-law = 20 ms; Twilio prefers multiples of this


def caller_hash(phone_number: str, secret: str) -> str:
    """HMAC-SHA256(phone_number, SERVER_SECRET), hex. The only form in which a number is kept."""
    return hash_number(phone_number, secret)


def media_token(call_sid: str, secret: str) -> str:
    """Per-call token that binds the media socket to the webhook that created it."""
    return hmac.new(secret.encode(), f"media:{call_sid}".encode(), hashlib.sha256).hexdigest()


def twilio_signature(url: str, params: dict[str, str], auth_token: str) -> str:
    """X-Twilio-Signature: base64(HMAC-SHA1(token, url + sorted key+value pairs))."""
    data = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    digest = hmac.new(auth_token.encode(), data.encode(), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def valid_signature(url: str, params: dict[str, str], header: str | None, auth_token: str) -> bool:
    if not header or not auth_token:
        return False
    return hmac.compare_digest(twilio_signature(url, params, auth_token), header)


def voice_twiml(ws_url: str, parameters: dict[str, str]) -> str:
    params = "".join(f"<Parameter name={quoteattr(k)} value={quoteattr(v)}/>" for k, v in parameters.items())
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f"<Response><Connect><Stream url={quoteattr(ws_url)}>{params}</Stream></Connect></Response>"
    )


class TwilioAdapter:
    """AudioAdapter over a Twilio Media Streams WebSocket (after the `start` event)."""

    def __init__(self, ws: WebSocket, stream_sid: str, tts_rate: int = 24000) -> None:
        if tts_rate != 24000:
            raise ValueError("TwilioAdapter expects 24 kHz TTS audio")
        self._ws = ws
        self.stream_sid = stream_sid
        self._up = Upsample2x()
        self._down = Downsample3x()
        self._pending = b""
        self._closed = False

    async def frames(self) -> AsyncIterator[bytes]:
        try:
            while True:
                raw = await self._ws.receive_text()
                msg = json.loads(raw)
                event = msg.get("event")
                if event == "media":
                    media = msg.get("media", {})
                    if media.get("track", "inbound") != "inbound":
                        continue
                    yield self._up.process(mulaw_to_pcm16(base64.b64decode(media["payload"])))
                elif event == "stop":
                    return
        except (WebSocketDisconnect, RuntimeError):
            return

    async def send(self, chunk: bytes) -> None:
        if self._closed:
            return
        self._pending += pcm16_to_mulaw(self._down.process(chunk))
        while len(self._pending) >= OUT_CHUNK:
            frame, self._pending = self._pending[:OUT_CHUNK], self._pending[OUT_CHUNK:]
            await self._media(frame)

    async def flush(self) -> None:
        """Send the sub-20 ms tail of an utterance (padded with mu-law silence)."""
        if self._pending and not self._closed:
            await self._media(self._pending.ljust(OUT_CHUNK, b"\xff"))
        self._pending = b""

    async def _media(self, mulaw: bytes) -> None:
        await self._ws.send_text(
            json.dumps(
                {
                    "event": "media",
                    "streamSid": self.stream_sid,
                    "media": {"payload": base64.b64encode(mulaw).decode()},
                }
            )
        )

    async def clear_output(self) -> None:
        self._pending = b""
        if not self._closed:
            await self._ws.send_text(json.dumps({"event": "clear", "streamSid": self.stream_sid}))

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            await self._ws.close()
        except RuntimeError:
            pass
