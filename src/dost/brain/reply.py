"""Builds reply prompts from call state."""

from __future__ import annotations

from dost.brain.lines import lines_for
from dost.brain.phases import CallState
from dost.brain.prompts import (
    CRISIS_ADDENDUM,
    CRISIS_FIRST_TURN,
    CRISIS_FOLLOWUP_TURN,
    LANGUAGE_RULES,
    REPLY_SYSTEM,
)
from dost.brain.safety import Risk

MAX_HISTORY = 20
_LANG = {"hi": "Hindi/Hinglish", "te": "Telugu", "en": "English"}


def system_prompt(state: CallState, risk: Risk, crisis_turn: int = 1) -> str:
    text = REPLY_SYSTEM.format(
        summary=state.summary or "(nothing yet; this is a first conversation)",
        open_loop=state.open_loop or "(none)",
        phase=state.phase,
        risk=risk.name.lower(),
        language=_LANG.get(state.language, state.language),
        language_rules=LANGUAGE_RULES.get(state.language, LANGUAGE_RULES["hi"]),
        address=state.address,
    )
    if risk < Risk.HIGH:
        return text
    turn = CRISIS_FIRST_TURN if crisis_turn <= 1 else CRISIS_FOLLOWUP_TURN
    return text + CRISIS_ADDENDUM + turn


def build_messages(
    state: CallState, history: list[dict], risk: Risk, crisis_turn: int = 1
) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt(state, risk, crisis_turn)},
        *history[-MAX_HISTORY:],
    ]


def safety_question(language: str) -> str:
    return lines_for(language).safety_q
