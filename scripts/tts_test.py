"""Phase 1: synthesize a line with bulbul:v4-flash over WebSocket and play it.

  uv run python scripts/tts_test.py                       # Hindi opener, VOICE_HI
  uv run python scripts/tts_test.py --lang te-IN --voice kavitha_te_conversation --text "..."
  uv run python scripts/tts_test.py --audition            # render candidate voices to out/

Writes a WAV to out/ (gitignored; dev artifact of synthesized speech, never caller audio).
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import subprocess
import time
import wave
from pathlib import Path

from dost.config import ROOT, load_settings
from dost.sarvam.tts import SarvamTTS

HI_OPENER = "हेलो, मैं दोस्त हूँ, एक AI आवाज़। जब मन करे, बात कर लेना। बताओ, क्या चल रहा है?"
TE_OPENER = "హలో, నేను దోస్త్ ని, ఒక AI వాయిస్ ని, మనిషిని కాదు. ఏం జరుగుతోంది, చెప్పు?"
HINGLISH = "अरे यार, फिर से? क्या हुआ, बता। मैं सुन रहा हूँ।"

AUDITION = [
    ("hi-IN", "amit_hi_conversational", HI_OPENER),
    ("hi-IN", "amit_hi_conversational", HINGLISH),
    ("hi-IN", "shubh_hi_customer", HI_OPENER),
    ("hi-IN", "ratan_hi_latenight_warm", HI_OPENER),
    ("te-IN", "tarun_te_narration", TE_OPENER),
    ("te-IN", "kavitha_te_conversation", TE_OPENER),
    ("te-IN", "pooja_te_conversation", TE_OPENER),
]


def play(path: Path) -> None:
    player = shutil.which("pw-play") or shutil.which("aplay") or shutil.which("ffplay")
    if player is None:
        print("no audio player found; open the WAV manually")
        return
    args = [player, str(path)] + (["-nodisp", "-autoexit"] if player.endswith("ffplay") else [])
    subprocess.run(args, check=False)


async def synth(tts: SarvamTTS, text: str, lang: str, voice: str, out: Path) -> None:
    t0 = time.perf_counter()
    first = None
    pcm = bytearray()
    async for chunk in tts.speak(text, lang, voice):
        if first is None:
            first = time.perf_counter() - t0
        pcm += chunk
    total = time.perf_counter() - t0
    out.parent.mkdir(exist_ok=True)
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(tts.sample_rate)
        w.writeframes(bytes(pcm))
    secs = len(pcm) / 2 / tts.sample_rate
    print(f"{voice:28s} {lang}  first chunk {first or 0:.2f}s  total {total:.2f}s  "
          f"audio {secs:.1f}s -> {out.relative_to(ROOT)}")


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--text", default=HI_OPENER)
    p.add_argument("--lang", default="hi-IN")
    p.add_argument("--voice")
    p.add_argument("--rate", type=int, default=24000)
    p.add_argument("--audition", action="store_true")
    p.add_argument("--no-play", action="store_true")
    a = p.parse_args()

    s = load_settings()
    tts = SarvamTTS(s.sarvam_api_key, sample_rate=a.rate)
    if a.audition:
        for i, (lang, voice, text) in enumerate(AUDITION):
            await synth(tts, text, lang, voice, ROOT / "out" / f"audition_{i}_{voice}.wav")
        return
    voice = a.voice or (s.voice_te if a.lang == "te-IN" else s.voice_hi)
    out = ROOT / "out" / f"tts_{voice}.wav"
    await synth(tts, a.text, a.lang, voice, out)
    if not a.no_play:
        play(out)


if __name__ == "__main__":
    asyncio.run(main())
