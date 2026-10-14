"""Analyzer LLM: one JSON object per caller turn. Failure degrades to the rule screen only."""

from __future__ import annotations

import logging
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from dost.brain.phases import CallState
from dost.brain.prompts import ANALYZER_SYSTEM, ANALYZER_USER
from dost.brain.safety import Risk
from dost.sarvam.llm import SarvamLLM

log = logging.getLogger("dost.analyzer")

TIMEOUT_S = 0.7  # analyzer gate: the reply waits at most this long for it


class Register(BaseModel):
    formality: Literal["casual", "neutral", "formal"] = "casual"
    address: Literal["tu", "tum", "aap", "na"] = "na"


class Analysis(BaseModel):
    model_config = {"populate_by_name": True}

    language: Literal["hi", "te", "en"] = "hi"
    reg: Register = Field(default_factory=Register, alias="register")
    emotion: str = ""
    risk: str = "none"
    risk_reasons: list[str] = Field(default_factory=list)
    phase: str = "exploring"
    wants_to_end: bool = False
    memory_facts: list[str] = Field(default_factory=list)
    open_loop: str | None = None

    @property
    def risk_level(self) -> Risk:
        return Risk.parse(self.risk)


def parse_analysis(data: dict) -> Analysis:
    try:
        return Analysis.model_validate(data)
    except ValidationError:
        # Keep what is salvageable: the safety-relevant fields matter most.
        return Analysis(
            risk=str(data.get("risk", "none")),
            wants_to_end=bool(data.get("wants_to_end", False)),
        )


def _turns(history: list[dict], n: int = 6) -> str:
    rows = history[-n:]
    return "\n".join(f"{'Caller' if m['role'] == 'user' else 'Dost'}: {m['content']}" for m in rows) or "(none)"


async def analyze(llm: SarvamLLM, state: CallState, history: list[dict], text: str) -> Analysis | None:
    """Returns None when the analyzer fails (caller falls back to the rule screen)."""
    user = ANALYZER_USER.format(
        phase=state.phase, language=state.language, address=state.address,
        turns=_turns(history), text=text,
    )
    messages = [
        {"role": "system", "content": ANALYZER_SYSTEM},
        {"role": "user", "content": user},
    ]
    for attempt in (1, 2):  # one retry: transient API errors or truncated JSON
        try:
            return parse_analysis(await llm.json(messages, max_tokens=400))
        except Exception as exc:
            log.warning("analyzer attempt %d failed: %s: %s", attempt, type(exc).__name__, exc)
    return None
