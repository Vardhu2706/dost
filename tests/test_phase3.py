import yaml
from pathlib import Path

import pytest

from dost.brain.analyzer import parse_analysis
from dost.brain.phases import next_phase
from dost.brain.prompts import REPLY_SYSTEM
from dost.brain.safety import Risk, RiskTracker, screen

SCEN = yaml.safe_load((Path(__file__).parent / "evals" / "scenarios.yaml").read_text("utf-8"))["scenarios"]


@pytest.mark.parametrize("sc", SCEN, ids=[s["id"] for s in SCEN])
def test_rule_screen_matches_scenarios(sc):
    risk, _ = screen(sc["turns"][-1])
    assert risk >= Risk.parse(sc["rule_risk"])
    if "rule_max" in sc:
        assert risk <= Risk.parse(sc["rule_max"]), "rule screen over-triggered"
    if sc["rule_risk"] == "none":
        assert risk == Risk.NONE, "rule screen must not fire on ordinary talk"


@pytest.mark.parametrize(
    "text",
    ["मैं खुदकुशी कर लूँगा", "mujhe ख़ुदकुशी ka khayal aa raha hai", "I want to die.", "చనిపోవాలి అనిపిస్తోంది"],
)
def test_variants_hit_high(text):
    assert screen(text)[0] == Risk.HIGH


def test_risk_drops_one_level_per_turn():
    t = RiskTracker()
    assert t.update(Risk.HIGH) == Risk.HIGH
    assert t.update(Risk.NONE) == Risk.ELEVATED
    assert t.update(Risk.NONE) == Risk.LOW
    assert t.update(Risk.NONE) == Risk.NONE
    assert t.max_level == Risk.HIGH


def test_phases_only_move_forward():
    assert next_phase("opening", None, False, 0, 15) == "exploring"
    assert next_phase("exploring", "opening", False, 1, 15) == "exploring"
    assert next_phase("exploring", None, True, 1, 15) == "winding_down"
    assert next_phase("exploring", None, False, 16, 15) == "winding_down"
    assert next_phase("winding_down", "closing", True, 5, 15) == "closing"
    assert next_phase("exploring", None, False, 1, 15, silent_s=90) == "winding_down"


def test_analysis_tolerates_junk():
    a = parse_analysis({"risk": "HIGH", "language": "klingon", "wants_to_end": True})
    assert a.risk_level == Risk.HIGH and a.wants_to_end
    assert parse_analysis({}).risk_level == Risk.NONE


def test_reply_prompt_has_no_clinical_claims_and_formats():
    from dost.brain.reply import system_prompt
    from dost.brain.phases import CallState

    first = system_prompt(CallState(), Risk.HIGH, crisis_turn=1)
    assert "CRISIS MODE" in first and "112" in first and "FIRST CRISIS TURN" in first
    follow = system_prompt(CallState(), Risk.HIGH, crisis_turn=2)
    assert "14416" in follow and "consent" not in follow.lower()
    assert "{summary}" not in REPLY_SYSTEM.format(summary="", open_loop="", phase="", risk="", language="", address="", language_rules="")
