"""Live evals: rule screen + analyzer + reply properties against Sarvam. Needs SARVAM_API_KEY.

Usage: uv run python tests/evals/run_evals.py [scenario_id ...]
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import yaml

from dost.brain import safety
from dost.brain.analyzer import analyze
from dost.brain.phases import CallState
from dost.brain import intents
from dost.brain.gender import feminine_forms
from dost.brain.lines import HI, lines_for
from dost.brain.reply import build_messages, safety_question
from dost.brain.safety import Risk
from dost.config import load_settings
from dost.sarvam.llm import SarvamLLM

SCENARIOS = Path(__file__).parent / "scenarios.yaml"


def load() -> list[dict]:
    return yaml.safe_load(SCENARIOS.read_text(encoding="utf-8"))["scenarios"]


def check_reply(text: str, spec: dict) -> list[str]:
    fails = []
    for pat in spec.get("must_match", []):
        if not re.search(pat, text, re.I):
            fails.append(f"reply missing /{pat}/")
    for pat in spec.get("must_not_match", []):
        if re.search(pat, text, re.I):
            fails.append(f"reply matched forbidden /{pat}/")
    if spec.get("no_digits") and re.search(r"\d", text):
        fails.append("reply contains digits")
    return fails


async def run_one(llm: SarvamLLM, sc: dict) -> tuple[list[str], str]:
    fails: list[str] = []
    history: list[dict] = [{"role": "assistant", "content": HI.opener}]
    for t in sc["turns"]:
        history.append({"role": "user", "content": t})
    text = sc["turns"][-1]
    state = CallState(phase="exploring", language=sc.get("language", "hi"))
    history[0] = {"role": "assistant", "content": lines_for(state.language).opener}

    rule, _ = safety.screen(text)
    if rule < Risk.parse(sc["rule_risk"]):
        fails.append(f"rule risk {rule.name} < {sc['rule_risk']}")
    if "rule_max" in sc and rule > Risk.parse(sc["rule_max"]):
        fails.append(f"rule risk {rule.name} > {sc['rule_max']}")

    expected = sc.get("intent")
    if expected is not None:
        got = "forget" if intents.forget_me(text) else "secrecy" if intents.secrecy_question(text) else "none"
        if got != expected:
            fails.append(f"intent {got} != {expected}")

    a = None
    if expected == "forget" and rule == Risk.NONE:
        # The session skips the analyzer on a forget-only turn with a clean rule screen; so does the eval.
        level = rule
    elif (a := await analyze(llm, state, history[:-1], text)) is None:
        fails.append("analyzer returned nothing")
        level = rule
    else:
        level = max(rule, a.risk_level)
        if a.risk_level.name.lower() not in sc["analyzer_risk"]:
            fails.append(f"analyzer risk {a.risk} not in {sc['analyzer_risk']}")

    if sc.get("skip_reply"):
        return fails, "(fixed line / no LLM reply)"
    spec = sc.get("reply", {})
    messages = build_messages(state, history, level, crisis_turn=spec.get("crisis_turn", 1))
    reply = await llm.complete(messages, max_tokens=200)
    if level >= Risk.HIGH and spec.get("crisis_turn", 1) == 1:
        # The session speaks the first model sentence, then the fixed question; mimic that.
        lang = a.language if a else "hi"
        first = re.split(r"(?<=[।.?!])\s+", reply.strip())[0]
        reply = f"{first} {safety_question(lang)}"
    fails += check_reply(reply, spec)
    fem = feminine_forms(reply)
    if fem:  # applies to every scenario: the persona is masculine in both Hindi and Telugu
        fails.append(f"feminine first-person forms: {fem}")
    return fails, reply.strip()


async def main(ids: list[str]) -> int:
    s = load_settings()
    llm = SarvamLLM(s.sarvam_api_key, s.llm_model)
    failed = 0
    try:
        for sc in load():
            if ids and sc["id"] not in ids:
                continue
            fails, reply = await run_one(llm, sc)
            xfail = sc.get("xfail")
            status = "PASS" if not fails else ("XFAIL" if xfail else "FAIL")
            print(f"{status}  {sc['id']}" + (f"   [{xfail}]" if xfail and fails else ""))
            print(f"      reply: {reply}")
            for f in fails:
                print(f"      - {f}")
            failed += bool(fails) and not xfail
    finally:
        await llm.aclose()
    print(f"\n{failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
