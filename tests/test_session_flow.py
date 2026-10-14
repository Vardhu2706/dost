import asyncio

from dost.brain.safety import Risk
from dost.config import Settings
from dost.session import Session


class FakeLLM:
    def __init__(self, analyzer: dict, analyzer_delay: float = 0.0):
        self.analyzer, self.delay = analyzer, analyzer_delay
        self.systems: list[str] = []

    async def stream(self, messages, max_tokens=300):
        self.systems.append(messages[0]["content"])
        crisis = "CRISIS MODE" in messages[0]["content"]
        for tok in (["क्या तुम सुरक्षित हो", "? "] if crisis else ["अरे यार", "। ", "क्या हुआ", "?"]):
            await asyncio.sleep(0.01)
            yield tok

    async def json(self, messages, max_tokens=500):
        await asyncio.sleep(self.delay)
        return self.analyzer

    async def aclose(self):
        pass


class FakeTTS:
    sample_rate = 24000

    def __init__(self):
        self.spoken: list[str] = []
        self.calls: list[tuple[str, str, str]] = []

    async def speak(self, text, lang, voice):
        self.spoken.append(text)
        self.calls.append((text, lang, voice))
        yield b"\x00\x00"

    async def cancel(self):
        pass


class FakeAdapter:
    def __init__(self):
        self.sent = 0
        self.cleared = 0

    async def send(self, chunk):
        self.sent += 1

    async def clear_output(self):
        self.cleared += 1


def _session(llm, tts):
    settings = Settings("k", "", ":memory:", "hi-IN", "v", "v", "m", 7, 15)
    return Session(settings=settings, adapter=FakeAdapter(), stt=None, tts=tts, llm=llm)


def test_rule_hit_goes_straight_to_crisis_without_analyzer():
    tts = FakeTTS()
    s = _session(FakeLLM({"risk": "none"}, analyzer_delay=5), tts)
    asyncio.run(asyncio.wait_for(s._handle_final("मैं मरना चाहता हूँ", 0.0), 3))
    assert s.risk.level == Risk.HIGH
    from dost.brain.lines import HI

    SAFETY_Q_HI = HI.safety_q

    assert tts.spoken == ["क्या तुम सुरक्षित हो?", SAFETY_Q_HI]


def test_analyzer_escalation_switches_to_crisis():
    tts = FakeTTS()
    s = _session(FakeLLM({"risk": "high", "risk_reasons": ["x"]}, analyzer_delay=0.05), tts)
    asyncio.run(asyncio.wait_for(s._handle_final("sab kuch bahut bhaari lag raha hai", 0.0), 3))
    assert s.risk.level == Risk.HIGH
    assert "अरे यार।" not in tts.spoken
    from dost.brain.lines import HI

    SAFETY_Q_HI = HI.safety_q

    assert tts.spoken[-1] == SAFETY_Q_HI


def test_normal_turn_updates_state_and_speaks():
    tts = FakeTTS()
    a = {"risk": "low", "language": "hi", "register": {"formality": "formal", "address": "aap"},
         "phase": "exploring", "memory_facts": ["झगड़ा हुआ"], "open_loop": None}
    s = _session(FakeLLM(a), tts)
    asyncio.run(asyncio.wait_for(s._handle_final("आज घर में झगड़ा हुआ", 0.0), 3))
    assert tts.spoken == ["अरे यार।", "क्या हुआ?"]
    assert s.state.address == "aap" and s.state.facts == ["झगड़ा हुआ"]
    assert s.state.phase == "exploring" and s.risk.level == Risk.LOW


def test_crisis_protocol_safety_question_then_number_by_second_turn():
    from dost.brain.lines import HI

    TELEMANAS_LINE_HI = HI.telemanas

    tts = FakeTTS()
    s = _session(FakeLLM({"risk": "high"}), tts)
    asyncio.run(asyncio.wait_for(s._handle_final("Ab jeene ka mann nahi karta.", 0.0), 3))
    assert s.crisis_turns == 1
    from dost.brain.lines import HI

    SAFETY_Q_HI = HI.safety_q

    assert tts.spoken[-1] == SAFETY_Q_HI  # first turn: the fixed direct safety question
    assert TELEMANAS_LINE_HI not in tts.spoken
    assert "CRISIS MODE" in s.llm.systems[-1] and "FIRST CRISIS TURN" in s.llm.systems[-1]

    # Second turn: a mild reply that no rule hits; analyzer still elevated -> still crisis mode.
    s.llm.analyzer = {"risk": "elevated"}
    asyncio.run(asyncio.wait_for(s._handle_final("pata nahi, bas akela hoon", 0.0), 3))
    assert s.crisis_turns == 2
    assert tts.spoken.index(TELEMANAS_LINE_HI) < len(tts.spoken) - 1  # number first, then the LLM turn
    assert "HAS BEEN SAID ALOUD" in s.llm.systems[-1]

    # Third turn: do not recite the number again unprompted.
    before = tts.spoken.count(TELEMANAS_LINE_HI)
    asyncio.run(asyncio.wait_for(s._handle_final("haan thoda theek hoon", 0.0), 3))
    assert tts.spoken.count(TELEMANAS_LINE_HI) == before == 1
