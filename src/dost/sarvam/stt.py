"""Saaras realtime streaming STT over WebSocket."""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from urllib.parse import urlencode

from websockets.asyncio.client import connect

STT_URL = "wss://api.sarvam.ai/speech-to-text-realtime/ws"


@dataclass(frozen=True)
class SpeechStart:
    pass


@dataclass(frozen=True)
class Partial:
    text: str
    lang: str | None


@dataclass(frozen=True)
class Final:
    text: str
    lang: str | None
    confidence: float | None


STTEvent = SpeechStart | Partial | Final


def build_url(
    language_code: str = "auto",
    model: str = "saaras:v3-realtime",
    stream_type: str = "fast",
    mode: str = "transcribe",
    sample_rate: int = 16000,
    silence_duration_ms: int = 500,
) -> str:
    params = {
        "language_code": language_code,
        "model": model,
        "stream_type": stream_type,
        "mode": mode,
        "encoding": "linear16",
        "sample_rate": sample_rate,
        "silence_duration_ms": silence_duration_ms,
    }
    return f"{STT_URL}?{urlencode(params)}"


def parse_event(msg: dict) -> STTEvent | None:
    """Map a server message to an STTEvent; returns None for events we ignore."""
    event = msg.get("event")
    if event == "vad.speech_start":
        return SpeechStart()
    if event == "transcript.partial":
        return Partial(text=msg.get("text", ""), lang=msg.get("language"))
    if event == "transcript.final":
        return Final(
            text=msg.get("text", ""),
            lang=msg.get("language"),
            confidence=msg.get("language_confidence"),
        )
    if event == "error" and msg.get("is_fatal"):
        raise RuntimeError(f"STT fatal error {msg.get('code')}: {msg.get('message')}")
    return None


class SarvamSTT:
    def __init__(self, api_key: str, **url_params: object) -> None:
        self._api_key = api_key
        self._url = build_url(**url_params)  # type: ignore[arg-type]
        self.on_raw = None  # optional callback(dict) for debugging

    async def stream(self, frames: AsyncIterator[bytes]) -> AsyncIterator[STTEvent]:
        """Send PCM16 frames, yield STT events until the server ends the session."""
        async with connect(
            self._url, additional_headers={"api-subscription-key": self._api_key}
        ) as ws:

            async def pump() -> None:
                async for frame in frames:
                    await ws.send(
                        json.dumps(
                            {"event": "audio_input", "audio": base64.b64encode(frame).decode()}
                        )
                    )
                await ws.send(json.dumps({"event": "end"}))

            sender = asyncio.create_task(pump())
            try:
                async for raw in ws:
                    msg = json.loads(raw)
                    if self.on_raw:
                        self.on_raw(msg)
                    if msg.get("event") == "session.end":
                        break
                    ev = parse_event(msg)
                    if ev is not None:
                        yield ev
            finally:
                sender.cancel()
