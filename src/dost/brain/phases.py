"""Call phase state machine and per-call state."""

from __future__ import annotations

from dataclasses import dataclass, field

PHASES = ("opening", "exploring", "winding_down", "closing")
LONG_SILENCE_S = 60.0


@dataclass
class CallState:
    phase: str = "opening"
    language: str = "hi"  # hi | te | en (analyzer vocabulary)
    address: str = "tum"  # tu | tum | aap
    formality: str = "casual"
    emotion: str = ""
    facts: list[str] = field(default_factory=list)
    open_loop: str | None = None
    summary: str = ""  # previous-call memory (Phase 4)
    user_turns: int = 0


def next_phase(
    current: str,
    suggested: str | None,
    wants_to_end: bool,
    elapsed_min: float,
    soft_wind_down_min: float,
    silent_s: float = 0.0,
) -> str:
    """Phases only move forward. Time and silence nudge to winding_down, never straight to closing."""
    idx = PHASES.index(current) if current in PHASES else 0
    target = idx
    if suggested in PHASES:
        target = max(target, PHASES.index(suggested))
    if wants_to_end:
        target = max(target, PHASES.index("winding_down"))
    if elapsed_min >= soft_wind_down_min or silent_s >= LONG_SILENCE_S:
        target = max(target, PHASES.index("winding_down"))
    if idx == 0 and target == 0:
        target = 1  # first caller turn leaves "opening"
    return PHASES[target]
