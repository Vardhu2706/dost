"""Bulbul v4 Flash streaming TTS over WebSocket.

One socket per utterance: the API has no in-band cancel, so `cancel()` closes the
socket (Sarvam's documented barge-in recipe) and the next `speak()` opens a fresh one.
"""

from __future__ import annotations

import base64
import json
import logging
import re
from collections.abc import AsyncIterator

from websockets.asyncio.client import ClientConnection, connect

log = logging.getLogger("dost.tts")

TTS_URL = "wss://api.sarvam.ai/text-to-speech/ws?model=bulbul:v4-flash&send_completion_event=true"
MAX_TEXT_CHARS = 2500


_ELLIPSIS = r"(?:\.{2,}|…)"
_DASH = r"(?:[—–]+|\s-+\s)"
_DEVANAGARI = re.compile(r"[\u0900-\u097F]")


def normalize_for_tts(text: str) -> str:
    """Plain punctuation only: ellipses and dashes read as breathy hesitation, so turn them into
    ordinary sentence ends and commas before synthesis (spoken history is left untouched)."""
    end = "।" if _DEVANAGARI.search(text) else "."
    t = re.sub(rf"[\s,]*(?:{_ELLIPSIS}|{_DASH})[\s,.।]*\Z", end, text.strip())
    t = re.sub(rf"\s*(?:{_ELLIPSIS}|{_DASH})\s*", ", ", t)
    t = re.sub(r",\s*(?=[,.?!।])", "", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def config_message(
    voice: str,
    lang: str,
    sample_rate: int = 24000,
    pace: float = 1.0,
    pitch: float = 0.0,
    loudness: float = 1.0,
) -> dict:
    return {
        "type": "config",
        "data": {
            "speaker": voice,
            "language_code": lang,
            "speech_sample_rate": sample_rate,
            "output_audio_codec": "linear16",  # raw PCM16 mono, content_type audio/pcm
            "pace": pace,
            "pitch": pitch,
            "loudness": loudness,
            "enable_preprocessing": True,
        },
    }


class SarvamTTS:
    def __init__(
        self,
        api_key: str,
        sample_rate: int = 24000,
        pace: float = 1.0,
        pitch: float = 0.0,
        loudness: float = 1.0,
    ) -> None:
        self._api_key = api_key
        self.sample_rate = sample_rate
        self.pace = pace
        self.pitch = pitch
        self.loudness = loudness
        self._ws: ClientConnection | None = None

    async def speak(self, text: str, lang: str, voice: str) -> AsyncIterator[bytes]:
        """Yield PCM16 mono chunks at `self.sample_rate` for `text`."""
        log.info("tts socket voice=%s code=%s rate=%d chars=%d", voice, lang, self.sample_rate, len(text))
        text = normalize_for_tts(text)
        if not text:
            return
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f"TTS text exceeds {MAX_TEXT_CHARS} chars; chunk by sentence")
        async with connect(
            TTS_URL, additional_headers={"api-subscription-key": self._api_key}
        ) as ws:
            self._ws = ws
            try:
                await ws.send(
                    json.dumps(
                        config_message(
                            voice, lang, self.sample_rate, self.pace, self.pitch, self.loudness
                        )
                    )
                )
                await ws.send(json.dumps({"type": "text", "data": {"text": text}}))
                await ws.send(json.dumps({"type": "flush"}))
                async for raw in ws:
                    msg = json.loads(raw)
                    kind = msg.get("type")
                    if kind == "audio":
                        yield base64.b64decode(msg["data"]["audio"])
                    elif kind == "event" and msg.get("data", {}).get("event_type") == "final":
                        return
                    elif kind == "error":
                        raise RuntimeError(f"TTS error: {msg.get('data')}")
            finally:
                self._ws = None

    async def cancel(self) -> None:
        if self._ws is not None:
            await self._ws.close()
