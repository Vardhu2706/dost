"""Phase 1: confirm the chat model ID and measure streaming latency.

  uv run python scripts/llm_test.py [--model sarvam-105b-conversations]
"""

from __future__ import annotations

import argparse
import asyncio
import time

from dost.config import load_settings
from dost.sarvam.llm import SarvamLLM

SYSTEM = (
    "You are Dost, a friendly AI voice on a phone call. Reply like a friend, in the "
    "caller's language and way of speaking, 1-2 short spoken sentences, no lists. "
    "Write Hindi words in Devanagari and English words in Latin script."
)
USER = "yaar aaj bahut bura laga, ghar mein phir jhagda ho gaya."


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--model")
    a = p.parse_args()
    s = load_settings()
    llm = SarvamLLM(s.sarvam_api_key, a.model or s.llm_model)
    msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": USER}]
    t0 = time.perf_counter()
    first = None
    out = []
    async for tok in llm.stream(msgs):
        first = first or time.perf_counter() - t0
        out.append(tok)
    print(f"[{llm.model}] first token {first or 0:.2f}s  total {time.perf_counter() - t0:.2f}s")
    print("reply:", "".join(out))
    t0 = time.perf_counter()
    js = await llm.json(
        [{"role": "system", "content": 'Return only JSON: {"language": "hi|te|en", "risk": "none|low|elevated|high", "emotion": "short label"}'},
         {"role": "user", "content": USER}]
    )
    print(f"json {time.perf_counter() - t0:.2f}s:", js)
    await llm.aclose()


if __name__ == "__main__":
    asyncio.run(main())
