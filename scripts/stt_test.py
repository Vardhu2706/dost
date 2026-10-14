"""Phase 1: stream audio to saaras:v3-realtime and print partials/finals with language.

  uv run python scripts/stt_test.py                 # live mic via arecord, Ctrl+C to stop
  uv run python scripts/stt_test.py --file out/x.wav  # 16-bit mono WAV (8k/16k, or resampled)
  uv run python scripts/stt_test.py --mode codemix --raw

Audio is streamed in memory only; nothing is written to disk.
"""

from __future__ import annotations

import argparse
import asyncio
import time
import wave
from collections.abc import AsyncIterator

from dost.config import load_settings
from dost.sarvam.stt import Final, Partial, SarvamSTT, SpeechStart

RATE = 16000
FRAME_BYTES = RATE * 2 // 10  # 100 ms of PCM16 mono


def resample_pcm16(pcm: bytes, src: int, dst: int) -> bytes:
    """Linear-interpolation resample; good enough for a test feed."""
    if src == dst:
        return pcm
    import array

    s = array.array("h", pcm)
    n = int(len(s) * dst / src)
    out = array.array("h", [0] * n)
    for i in range(n):
        x = i * src / dst
        j = int(x)
        f = x - j
        a = s[j]
        b = s[j + 1] if j + 1 < len(s) else a
        out[i] = int(a + (b - a) * f)
    return out.tobytes()


async def file_frames(path: str) -> AsyncIterator[bytes]:
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, "need 16-bit mono WAV"
        pcm = resample_pcm16(w.readframes(w.getnframes()), w.getframerate(), RATE)
    pcm += b"\x00" * RATE * 2  # 1 s trailing silence so server VAD closes the turn
    for i in range(0, len(pcm), FRAME_BYTES):
        yield pcm[i : i + FRAME_BYTES]
        await asyncio.sleep(0.1)  # real-time pacing


async def mic_frames() -> AsyncIterator[bytes]:
    proc = await asyncio.create_subprocess_exec(
        "arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw",
        stdout=asyncio.subprocess.PIPE,
    )
    assert proc.stdout
    print("listening on the default mic... speak Hindi/Hinglish/Telugu. Ctrl+C to stop.")
    try:
        while chunk := await proc.stdout.readexactly(FRAME_BYTES):
            yield chunk
    finally:
        proc.kill()


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--file")
    p.add_argument("--lang", default="auto")
    p.add_argument("--mode", default="transcribe")
    p.add_argument("--raw", action="store_true", help="print raw server events")
    a = p.parse_args()

    stt = SarvamSTT(load_settings().sarvam_api_key, language_code=a.lang, mode=a.mode)
    if a.raw:
        stt.on_raw = lambda m: print("  raw:", m)
    frames = file_frames(a.file) if a.file else mic_frames()
    t0 = time.perf_counter()
    async for ev in stt.stream(frames):
        t = time.perf_counter() - t0
        if isinstance(ev, SpeechStart):
            print(f"[{t:5.1f}s] speech_start")
        elif isinstance(ev, Partial):
            print(f"[{t:5.1f}s] partial ({ev.lang}): {ev.text}")
        elif isinstance(ev, Final):
            print(f"[{t:5.1f}s] FINAL   ({ev.lang}, conf={ev.confidence}): {ev.text}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
