"""Post-call summarizer: merges the previous summary with a call into <= 80 words + one open loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from dost.sarvam.llm import SarvamLLM

log = logging.getLogger("dost.summarizer")

MAX_WORDS = 80

SYSTEM = """You maintain a short private memory for a friendly voice companion called Dost.
Merge the PREVIOUS SUMMARY with the CALL TRANSCRIPT into one updated summary, in English, at most 80 words.
Rules:
- Keep only durable, useful context (what is going on in their life, what helps, what they said they will do).
- No names, phone numbers, addresses or other identifiers. No diagnoses or labels. No clinical language.
- Do not quote the caller's most painful words; describe gently and neutrally.
- If the caller asked to be forgotten, or said not to remember something, leave that out.
Also give ONE open_loop: something the CALLER themselves said they would do or wanted to report back on \
(for example "will talk to his brother and tell how it went"). Never invent one and never pick one yourself \
on their behalf. Use null if the caller did not choose one.
Return ONLY JSON: {"summary": "...", "open_loop": "..." or null}"""


@dataclass(frozen=True)
class Summary:
    summary: str
    open_loop: str | None


def cap_words(text: str, n: int = MAX_WORDS) -> str:
    words = text.split()
    return text.strip() if len(words) <= n else " ".join(words[:n]).rstrip(",;:") + "…"


def _clean_loop(v: object) -> str | None:
    if not isinstance(v, str):
        return None
    v = v.strip()
    return None if v.lower() in ("", "null", "none", "n/a") else cap_words(v, 25)


def fallback_summary(previous: str, facts: list[str], open_loop: str | None) -> Summary:
    """No LLM: previous summary plus the analyzer's facts, capped. Open loop from the analyzer."""
    merged = " ".join(p for p in [previous.strip(), "; ".join(facts)] if p)
    return Summary(cap_words(merged), _clean_loop(open_loop))


async def summarize(
    llm: SarvamLLM, previous: str, turns: list[tuple[str, str]], facts: list[str], loop_hint: str | None
) -> Summary:
    transcript = "\n".join(f"{'Caller' if r == 'user' else 'Dost'}: {t}" for r, t in turns)
    user = f"PREVIOUS SUMMARY:\n{previous or '(none)'}\n\nCALL TRANSCRIPT:\n{transcript}"
    try:
        data = await llm.json(
            [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], max_tokens=300
        )
        summary = cap_words(str(data.get("summary", "")))
        if not summary:
            raise ValueError("empty summary")
        return Summary(summary, _clean_loop(data.get("open_loop")))
    except Exception as exc:
        log.warning("summarizer failed (%s: %s); using fallback", type(exc).__name__, exc)
        return fallback_summary(previous, facts, loop_hint)
