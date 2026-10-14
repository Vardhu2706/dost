"""FastAPI gateway: serves the call UI and one WebSocket per call."""

from __future__ import annotations

import logging
from pathlib import Path

import asyncio
import json
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from dost.audio.browser import BrowserWSAdapter
from dost.audio.twilio import (
    TwilioAdapter,
    media_token,
    valid_signature,
    voice_twiml,
)
from dost.config import load_settings
from dost.memory.db import Memory
from dost.memory.models import hash_number
from dost.phone import RateLimiter, callback_configured, place_callback, secret_ok
from dost.sarvam.llm import SarvamLLM
from dost.sarvam.stt import SarvamSTT
from dost.sarvam.tts import SarvamTTS
from dost.session import Session

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("dost")

WEB = Path(__file__).parent / "web"
TTS_RATE = 24000

app = FastAPI(title="Dost")
app.mount("/static", StaticFiles(directory=WEB), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.websocket("/ws/call")
async def call(ws: WebSocket) -> None:
    settings = load_settings()
    if settings.server_secret and ws.query_params.get("token") != settings.server_secret:
        await ws.close(code=1008)
        return
    await ws.accept()
    # First message from the page: {"type": "start", "number": "<typed demo number or empty>"}.
    # The number is hashed immediately; with no number (or no SERVER_SECRET) the call keeps nothing.
    number = ""
    try:
        first = await asyncio.wait_for(ws.receive(), timeout=5)
        if first.get("text"):
            msg = json.loads(first["text"])
            if msg.get("type") == "start":
                number = str(msg.get("number", ""))
    except (asyncio.TimeoutError, ValueError, WebSocketDisconnect, RuntimeError):
        pass
    digits = "".join(c for c in number if c.isdigit())
    caller = hash_number(number, settings.server_secret) if len(digits) >= 6 and settings.server_secret else None
    del number, digits
    adapter = BrowserWSAdapter(ws, out_sample_rate=TTS_RATE)
    await adapter.start()
    session = _build_session(settings, adapter, caller_hash=caller)
    log.info("call started memory=%s", caller is not None)
    try:
        await session.run()
    except Exception:
        log.exception("call failed")
    finally:
        log.info("call ended")


_memory: Memory | None = None


def get_memory(settings) -> Memory:
    global _memory
    if _memory is None:
        _memory = Memory(settings.db_path, ttl_days=settings.transcript_ttl_days)
    return _memory


def _build_session(settings, adapter, caller_hash: str | None = None) -> Session:
    return Session(
        settings=settings,
        adapter=adapter,
        stt=SarvamSTT(
            settings.sarvam_api_key, language_code="auto", mode="codemix", stream_type="fast"
        ),
        tts=SarvamTTS(settings.sarvam_api_key, sample_rate=TTS_RATE),
        llm=SarvamLLM(settings.sarvam_api_key, settings.llm_model),
        caller_hash=caller_hash,
        memory=get_memory(settings) if caller_hash else None,
    )


# --- Phone leg (Twilio Media Streams) -----------------------------------------------------------


_call_limiter = RateLimiter()


@app.post("/call-me")
async def call_me(request: Request) -> Response:
    """Ring the verified CALLBACK_NUMBER from TWILIO_NUMBER. No body: the destination is env-only."""
    settings = load_settings()
    if not secret_ok(request.headers.get("X-Server-Secret"), settings.server_secret):
        return Response("forbidden", status_code=403)
    if not callback_configured(settings):
        return Response("callback not configured", status_code=503)
    wait = _call_limiter.retry_after()
    if wait > 0:
        return Response(
            "rate limited", status_code=429, headers={"Retry-After": str(int(wait) + 1)}
        )
    _call_limiter.record()  # count the attempt even if Twilio rejects it
    try:
        sid = await place_callback(settings)
    except Exception:
        log.exception("callback failed")
        return Response("callback failed", status_code=502)
    log.info("callback placed sid=%s", sid)
    return Response(json.dumps({"call_sid": sid}), media_type="application/json")


@app.post("/twilio/voice")
async def twilio_voice(request: Request) -> Response:
    """'A call comes in' webhook: validate the signature, return TwiML that opens the media stream."""
    settings = load_settings()
    if not (settings.public_base_url and settings.twilio_auth_token and settings.server_secret):
        return Response("Twilio leg not configured", status_code=503)
    # Twilio posts x-www-form-urlencoded; parse by hand to avoid a python-multipart dependency.
    form = dict(parse_qsl((await request.body()).decode(), keep_blank_values=True))
    sig = request.headers.get("X-Twilio-Signature")
    if not valid_signature(f"{settings.public_base_url}/twilio/voice", form, sig, settings.twilio_auth_token):
        return Response("bad signature", status_code=403)
    from dost.audio.twilio import caller_hash  # local import keeps the name free for the param

    call_sid = form.get("CallSid", "")
    ws_url = settings.public_base_url.replace("https://", "wss://").replace("http://", "ws://")
    twiml = voice_twiml(
        f"{ws_url}/twilio/media",
        {
            # The raw number never leaves this handler; only its HMAC goes into the stream.
            # Outbound (callback) calls have From=our number; the human is `To`.
            "caller_hash": caller_hash(
                form.get("To", "") if form.get("Direction", "").startswith("outbound") else form.get("From", ""),
                settings.server_secret,
            ),
            "call_sid": call_sid,
            "token": media_token(call_sid, settings.server_secret),
        },
    )
    return Response(twiml, media_type="text/xml")


@app.websocket("/twilio/media")
async def twilio_media(ws: WebSocket) -> None:
    settings = load_settings()
    await ws.accept()
    try:
        # Twilio sends `connected` then `start`; the start carries our custom parameters.
        start = None
        for _ in range(3):
            msg = json.loads(await ws.receive_text())
            if msg.get("event") == "start":
                start = msg["start"]
                break
        if start is None:
            await ws.close(code=1008)
            return
        params = start.get("customParameters", {})
        expected = media_token(params.get("call_sid", ""), settings.server_secret)
        if not settings.server_secret or params.get("token") != expected:
            await ws.close(code=1008)
            return
    except (WebSocketDisconnect, ValueError):
        return
    adapter = TwilioAdapter(ws, stream_sid=start["streamSid"], tts_rate=TTS_RATE)
    session = _build_session(settings, adapter, caller_hash=params.get("caller_hash"))
    log.info("phone call started")
    try:
        await session.run()
    except Exception:
        log.exception("phone call failed")
    finally:
        log.info("phone call ended")


def run() -> None:
    import uvicorn

    uvicorn.run("dost.main:app", host="127.0.0.1", port=8000)


if __name__ == "__main__":
    run()
