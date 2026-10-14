"""Voice audition: the same three lines through each candidate voice, to listen and pick.

  uv run python scripts/voice_audition.py                 # Hindi (default): male Hindi candidates
  uv run python scripts/voice_audition.py --lang en       # English set, en-IN
  uv run python scripts/voice_audition.py --lang te       # Telugu set, lines from lines.py only
  uv run python scripts/voice_audition.py --lang en --only dev sunny

Writes numbered WAVs to out/audition/ (gitignored; synthesized speech, never caller audio) and prints
a table: file number, voice, gender, params, line. Params are the ones bulbul:v4-flash supports (pace
0.5-2.0, pitch -0.5-0.5, loudness 0.1-2.5; no temperature). Gender is inferred from names on the
Voices page, which does not state it. Does not change any default voice.
"""

from __future__ import annotations

import argparse
import asyncio
import wave

from dost.brain.lines import EN, HI, TE
from dost.config import ROOT, load_settings
from dost.sarvam.tts import SarvamTTS

CURRENT = "shubh_enhi_companion"
AMIT = "amit_hi_conversational"

# Per language: TTS language code, three (name, text) lines, and (voice, gender) candidates.
# Telugu text comes only from lines.py (needs native-speaker review); do not write new Telugu here.
SETS = {
    "hi": {
        "code": "hi-IN",
        "lines": [
            ("opener", HI.opener),
            ("venting", "अरे यार, फिर से? क्या हुआ, बता।"),
            ("crisis", HI.telemanas),
        ],
        "voices": [(v, "male") for v in (
            CURRENT, "aayan_hi_conversational", "amit_hi_conversational", "ashutosh_hi_conversational",
            "kabir_hi_conversational", "manan_hi_conversational", "rahul_hi_conversational",
            "sumit_hi_conversational", "aditya_hi_conversational", "mani_hi_conversational",
            "mohit_hi_conversational", "tarun_hi_conversational", "rehan_hi_social", "ratan_hi_social",
        )],
    },
    "en": {
        "code": "en-IN",
        "lines": [
            ("opener", EN.opener),
            ("venting", "Oh man, again? What happened? Tell me."),
            ("crisis", EN.telemanas),
        ],
        # Male en / enhi voices closest to a conversational friend; the rest of the male roster is
        # ads, sports, news, narration, suspense or kids and was left out to stay near 40 TTS calls.
        "voices": [(v, "male") for v in (
            AMIT, CURRENT, "dev_en_conversational", "deven_en_conversation", "sunny_enhi_customer",
            "ojas_en_social", "sunny_en_social", "rohan_en_recovery",
        )],
    },
    "te": {
        "code": "te-IN",
        "lines": [
            ("opener", TE.opener),
            ("reply", TE.crisis_fallback[0]),
            ("crisis", TE.telemanas),
        ],
        "voices": [
            ("tarun_te_narration", "male"), ("kavitha_te_conversation", "female"),
            ("kavitha_te_narration", "female"), ("pooja_te_conversation", "female"), (AMIT, "male"),
        ],
    },
}


async def synth(tts: SarvamTTS, text: str, code: str, voice: str) -> bytes:
    return b"".join([c async for c in tts.speak(text, code, voice)])


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=sorted(SETS), default="hi")
    ap.add_argument("--only", nargs="*", help="substrings of voice ids to include")
    a = ap.parse_args()
    spec = SETS[a.lang]
    key = load_settings().sarvam_api_key
    out = ROOT / "out" / "audition"
    out.mkdir(parents=True, exist_ok=True)

    voices = [(v, g) for v, g in spec["voices"] if not a.only or any(s in v for s in a.only)]
    tts = SarvamTTS(key)  # defaults only: pace 1.0, pitch 0, loudness 1.0
    print(f"{'file':>4}  {'voice':30} {'gender':7} {'params':9} line")
    n = 0
    for voice, gender in voices:
        for name, text in spec["lines"]:
            n += 1
            try:
                pcm = await synth(tts, text, spec["code"], voice)
            except Exception as e:  # keep going; one bad voice id should not stop the audition
                print(f"{n:>4}  {voice:30} {gender:7} {'defaults':9} {name}  FAILED: {e}")
                continue
            path = out / f"{a.lang}_{n:02d}_{voice}_{name}.wav"
            with wave.open(str(path), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(tts.sample_rate)
                w.writeframes(pcm)
            print(f"{n:>4}  {voice:30} {gender:7} {'defaults':9} {name}  {path.name}")


if __name__ == "__main__":
    asyncio.run(main())
