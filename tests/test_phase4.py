import asyncio
import time

import pytest

from dost.brain import intents
from dost.brain.gender import feminine_forms
from dost.brain.intents import LangTracker
from dost.brain.lines import EN, HI, LINES, TE
from dost.config import Settings
from dost.memory.db import Memory
from dost.memory.models import hash_number
from dost.memory.summarizer import cap_words, fallback_summary, summarize
from dost.sarvam.stt import Final
from dost.session import Session

# --- intents ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text", ["bhool jao", "Mujhe bhool jao please", "भूल जाओ", "forget me", "Forget it.", "మర్చిపో", "sab bhool jao"]
)
def test_forget_me_positive(text):
    assert intents.forget_me(text)


@pytest.mark.parametrize(
    "text",
    [
        "usse bhool jao yaar, wo tumhare layak nahi", "నేను మర్చిపోయాను",
        "main kal ki baat bhool jaana chahta hoon par bhool nahi pa raha, bahut kuch hua hai ghar mein",
        "kuch nahi",
    ],
)
def test_forget_me_negative(text):
    assert not intents.forget_me(text)


@pytest.mark.parametrize(
    "text",
    ["kisi ko mat batana, promise karo", "will you keep this secret?", "यह राज़ रखोगे ना? किसी को नहीं बताओगे?",
     "ఇది ఎవరికీ చెప్పకు, రహస్యం"],
)
def test_secrecy_question(text):
    assert intents.secrecy_question(text)


def test_secrecy_negative():
    assert not intents.secrecy_question("आज office में बहुत काम था")


@pytest.mark.parametrize(
    "text,lang",
    [("please english mein baat karo", "en"), ("can you speak in english", "en"), ("हिंदी में बात करो", "hi"),
     ("తెలుగులో మాట్లాడు", "te"), ("telugu lo matladu", "te")],
)
def test_requested_language(text, lang):
    assert intents.requested_language(text) == lang


def test_requested_language_needs_a_request():
    assert intents.requested_language("mujhe english mein email likhna hai") is None
    assert intents.requested_language("english mein movie dekhna pasand karta hoon") is None
    assert intents.requested_language("आज का दिन अच्छा था") is None


def test_language_switches_only_after_two_consecutive_confident_finals():
    t = LangTracker(current="hi")
    assert not t.observe("te-IN", 0.9)  # first final in Telugu: stay in Hindi
    assert not t.observe("hi-IN", 0.9)  # back: the count resets
    assert not t.observe("te-IN", 0.9)
    assert not t.observe("en-IN", 0.2)  # low confidence is ignored, neither counts nor resets
    assert t.observe("te-IN", 0.8)  # second consecutive Telugu final
    assert t.current == "te"
    assert t.request("en") and t.current == "en"  # explicit request switches at once


# --- masculine forms ----------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["मैं सुन रही हूँ", "मैं समझ सकती हूँ", "मैं बात करती हूं", "मैं कल गई थी", "నేను ఒక అమ్మాయిని"])
def test_feminine_forms_detected(bad):
    assert feminine_forms(bad), bad


@pytest.mark.parametrize("good", ["मैं सुन रहा हूँ", "मैं समझ सकता हूँ", "मैं यहीं हूँ, तुम्हारे साथ।", "बारिश हो रही है।"])
def test_masculine_forms_pass(good):
    assert feminine_forms(good) == []


def test_all_fixed_lines_are_masculine_and_have_every_language():
    assert set(LINES) == {"hi", "en", "te"}
    for lines in (HI, EN, TE):
        for value in lines.__dict__.values():
            for text in (value if isinstance(value, tuple) else (value,)):
                assert feminine_forms(text) == [], text
    assert HI.opener == "हेलो, मैं दोस्त हूँ, एक AI आवाज़। जब मन करे, बात कर लेना। बताओ, क्या चल रहा है?"
    assert TE.opener == "హలో, నేను దోస్త్ ని, ఒక AI వాయిస్ ని, మనిషిని కాదు. ఏం జరుగుతోంది, చెప్పు?"


def test_secrecy_line_matches_memory_behaviour_and_says_ai():
    for lines in (HI, EN, TE):
        assert "AI" in lines.secrecy and "AI" in lines.secrecy_no_memory
    assert "forget" in EN.secrecy.lower() and "summary" in EN.secrecy.lower()
    assert "don't keep anything" in EN.secrecy_no_memory


# --- memory ---------------------------------------------------------------------------------------


def test_hash_ignores_formatting_and_never_contains_number():
    a = hash_number("+91 98765-43210", "k")
    assert a == hash_number("+919876543210", "k") and "9876543210" not in a
    assert a != hash_number("+919876543210", "other-key")


def test_memory_roundtrip_forget_and_ttl():
    m = Memory(":memory:", ttl_days=7)
    m.start_call("c1", "h1", started_at=100)
    m.add_turn("c1", 0, "user", "hello", "hi", now=100)
    m.add_risk_event("c1", "high", ts=101)
    m.end_call("c1", "closing", "high", ended_at=200)
    m.save_summary("h1", "likes chai", "will call brother", "hi", now=200)
    u = m.get_user("h1")
    assert u and u.summary == "likes chai" and u.open_loop == "will call brother" and u.call_count == 1
    m.save_summary("h1", "likes tea", None, "te", now=300)
    assert m.get_user("h1").call_count == 2 and m.get_user("h1").open_loop is None
    assert m.pending_calls("h1") == ["c1"]
    assert m.forget("h1") is True
    assert m.get_user("h1") is None and m.transcript("c1") == [] and m.risk_events("c1") == []
    assert m.forget("h1") is False
    m.start_call("c2", "h2", 1)
    m.add_turn("c2", 0, "user", "old", "hi", now=time.time() - 8 * 86400)
    m.purge_expired()
    assert m.transcript("c2") == []


def test_cap_words_and_fallback():
    long = " ".join(["word"] * 120)
    assert len(cap_words(long).replace("…", "").split()) <= 80
    fb = fallback_summary("prev", ["a fact"], "null")
    assert fb.open_loop is None and "prev" in fb.summary and "a fact" in fb.summary


class StubLLM:
    def __init__(self, data=None, text="कैसा रहा, भाई से बात हुई?", fail=False):
        self.data, self.text, self.fail = data, text, fail
        self.systems: list[str] = []

    async def json(self, messages, max_tokens=500):
        if self.fail:
            raise RuntimeError("down")
        return self.data

    async def complete(self, messages, max_tokens=500):
        self.systems.append(messages[0]["content"])
        return self.text

    async def stream(self, messages, max_tokens=300):
        self.systems.append(messages[0]["content"])
        for tok in ["ठीक है", "। ", "बताओ", "।"]:
            yield tok

    async def aclose(self):
        pass


def test_summarizer_caps_and_cleans_open_loop():
    llm = StubLLM({"summary": " ".join(["w"] * 200), "open_loop": "null"})
    r = asyncio.run(summarize(llm, "", [("user", "hi")], [], None))
    assert len(r.summary.replace("…", "").split()) <= 80 and r.open_loop is None
    llm = StubLLM({"summary": "ok", "open_loop": "will talk to his brother"})
    assert asyncio.run(summarize(llm, "", [("user", "hi")], [], None)).open_loop == "will talk to his brother"
    r = asyncio.run(summarize(StubLLM(fail=True), "prev", [("user", "hi")], ["f"], "do x"))
    assert r.open_loop == "do x" and "prev" in r.summary


# --- session: opener, memory, language, forget ----------------------------------------------------


class FakeTTS:
    sample_rate = 24000

    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def speak(self, text, lang, voice):
        self.calls.append((text, lang, voice))
        yield b"\x00\x00"

    async def cancel(self):
        pass


class FakeAdapter:
    async def send(self, chunk):
        pass

    async def clear_output(self):
        pass

    async def close(self):
        pass


def _settings():
    return Settings("k", "s", ":memory:", "hi-IN", "V_HI", "V_TE", "m", 7, 15, voice_en="V_EN")


def _session(llm, mem, caller="h1"):
    return Session(settings=_settings(), adapter=FakeAdapter(), stt=None, tts=FakeTTS(), llm=llm,
                   caller_hash=caller, memory=mem)


def _run(s, coro):
    return asyncio.run(asyncio.wait_for(coro, 5))


def test_first_call_opener_discloses_ai_then_memory_line_then_question():
    mem = Memory(":memory:")
    s = _session(StubLLM(), mem)
    s.user = None
    _run(s, s._opening())
    spoken = [c[0] for c in s.tts.calls]
    assert spoken == [HI.opener_a, HI.memory_first_call, HI.opener_q]
    assert "AI" in spoken[0]  # disclosure is the very first line
    assert s.tts.calls[0][1:] == ("hi-IN", "V_HI")


def test_no_number_means_no_memory_line():
    s = _session(StubLLM(), None, caller=None)
    _run(s, s._opening())
    assert [c[0] for c in s.tts.calls] == [HI.opener_a, HI.opener_q]


def test_returning_caller_gets_open_loop_sentence_after_disclosure():
    from dost.memory.models import UserRecord

    mem = Memory(":memory:")
    s = _session(StubLLM(text="भाई से बात हुई, कैसा रहा?"), mem)
    s.user = UserRecord("h1", 1, "hi", "talks about work stress", "will talk to his brother", 2, 3)
    s.state.summary, s.state.open_loop = s.user.summary, s.user.open_loop
    _run(s, s._opening())
    spoken = [c[0] for c in s.tts.calls]
    assert spoken == [HI.opener_a, "भाई से बात हुई, कैसा रहा?"]
    assert "will talk to his brother" in s.llm.systems[-1]


def test_returning_caller_without_open_loop_or_llm_falls_back_to_fixed_lines():
    from dost.memory.models import UserRecord

    s = _session(StubLLM(text=""), Memory(":memory:"))
    s.user = UserRecord("h1", 1, "hi", "x", "an open loop", 2, 3)
    s.state.open_loop = "an open loop"
    _run(s, s._opening())
    assert [c[0] for c in s.tts.calls] == [HI.opener_a, HI.welcome_back, HI.opener_q]


def test_language_switch_changes_voice_code_prompt_and_fixed_lines_together():
    s = _session(StubLLM(), None, caller=None)
    s.state.language = "hi"
    s._tracker.current = "hi"
    for _ in range(2):
        s._update_language(Final("ఈ రోజు చాలా కష్టంగా అనిపించింది", "te-IN", 0.9))
    assert s.state.language == "te"
    _run(s, s._say_fixed([s.L.opener_q]))
    assert s.tts.calls[-1] == (TE.opener_q, "te-IN", "V_TE")
    from dost.brain.reply import system_prompt
    from dost.brain.safety import Risk

    assert "Telugu" in system_prompt(s.state, Risk.NONE)
    s._update_language(Final("please english mein baat karo", "hi-IN", 0.9))
    assert s.state.language == "en" and s._tts_lang() == "en-IN" and s._voice() == "V_EN"


def test_secrecy_question_is_a_fixed_line_not_llm_generated():
    class NoLLM(StubLLM):
        async def stream(self, messages, max_tokens=300):
            raise AssertionError("LLM must not be called for the secrecy line")
            yield

    s = _session(NoLLM(), Memory(":memory:"))
    _run(s, s._handle_final("किसी को मत बताना, promise करो", 0.0))
    assert [c[0] for c in s.tts.calls] == [HI.secrecy]
    s2 = _session(NoLLM(), None, caller=None)
    _run(s2, s2._handle_final("will you keep this secret?", 0.0))
    assert s2.tts.calls[0][0] == HI.secrecy_no_memory


def test_forget_me_deletes_record_confirms_and_nothing_is_written_after():
    mem = Memory(":memory:")
    mem.save_summary("h1", "old summary", "loop", "hi")
    s = _session(StubLLM({"summary": "NEW", "open_loop": None}), mem)
    s.user = mem.get_user("h1")
    mem.start_call(s.call_id, "h1")
    _run(s, s._handle_final("bhool jao", 0.0))
    assert [c[0] for c in s.tts.calls] == [HI.forgot]
    assert mem.get_user("h1") is None and s.forgotten and not s.memory_active
    s.state.user_turns = 3
    _run(s, s._finish())
    assert mem.get_user("h1") is None  # the post-call step must not resurrect the record


def test_finish_saves_summary_and_deletes_transcript():
    mem = Memory(":memory:")
    s = _session(StubLLM({"summary": "work stress, wants to talk to brother", "open_loop": "talk to brother"}), mem)
    mem.start_call(s.call_id, "h1")
    s.state.user_turns, s.state.language = 2, "te"
    s._record("user", "ఆఫీస్ లో చాలా ఒత్తిడి")
    s._record("assistant", "అరె, ఏం జరిగింది?")
    _run(s, s._finish())
    u = mem.get_user("h1")
    assert u and u.open_loop == "talk to brother" and u.language_pref == "te" and u.call_count == 1
    assert mem.transcript(s.call_id) == []  # only the summary is kept


def test_no_memory_call_stores_nothing():
    s = _session(StubLLM(), None, caller=None)
    s.state.user_turns = 2
    s._record("user", "hello")  # no-op without memory
    _run(s, s._finish())


def test_forget_only_turn_never_enters_crisis_or_writes_risk_event():
    class NoLLM(StubLLM):
        async def json(self, messages, max_tokens=500):
            raise AssertionError("analyzer must not run on a forget-only turn")

        async def stream(self, messages, max_tokens=300):
            raise AssertionError("reply LLM must not run on a forget-only turn")
            yield

    mem = Memory(":memory:")
    mem.save_summary("h1", "old", "loop", "hi")
    s = _session(NoLLM(), mem)
    s.user = mem.get_user("h1")
    mem.start_call(s.call_id, "h1")
    _run(s, s._handle_final("bhool jao", 0.0))
    assert [c[0] for c in s.tts.calls] == [HI.forgot]
    assert s.crisis_turns == 0 and s.risk.max_level.name == "NONE"
    assert mem.get_user("h1") is None
    assert mem.risk_events(s.call_id) == []


def test_forget_with_crisis_content_goes_to_crisis_first():
    mem = Memory(":memory:")
    mem.save_summary("h1", "old", "loop", "hi")
    s = _session(StubLLM(), mem)
    s.user = mem.get_user("h1")
    mem.start_call(s.call_id, "h1")
    _run(s, s._handle_final("bhool jao, main marna chahta hoon", 0.0))
    spoken = [c[0] for c in s.tts.calls]
    assert HI.forgot not in spoken and not s.forgotten
    assert s.crisis_turns >= 1 and s.risk.max_level.name == "HIGH"
    assert mem.get_user("h1") is not None  # forget waits for the following turn


def test_dwell_after_switch_blocks_auto_switch_for_three_turns():
    t = LangTracker(current="hi")
    t.observe("te-IN", 0.9)
    assert t.observe("te-IN", 0.9) and t.current == "te"
    for _ in range(3):  # three caller turns: two consecutive Hindi finals would normally switch
        assert not t.observe("hi-IN", 0.9)
    assert t.current == "te"
    assert not t.observe("hi-IN", 0.9)  # 4th turn after the switch: counting starts again
    assert t.observe("hi-IN", 0.9) and t.current == "hi"


def test_dwell_does_not_block_an_explicit_request():
    t = LangTracker(current="hi")
    t.observe("te-IN", 0.9)
    t.observe("te-IN", 0.9)
    assert t.request("en") and t.current == "en"




def _te_session(llm, mem=None, caller=None):
    s = _session(llm, mem, caller=caller)
    s.state.language = "te"
    s._tracker.current = "te"
    return s


def test_all_chunks_of_one_reply_use_the_same_voice_and_code():
    s = _te_session(StubLLM())
    seen: list[tuple[str, str]] = []
    orig = s.tts.speak

    async def spy(text, lang, voice):
        seen.append((lang, voice))
        # the caller's language flips mid-reply (e.g. a late detection): chunks must not follow it
        s.state.language = "hi" if len(seen) == 1 else "en"
        async for c in orig(text, lang, voice):
            yield c

    s.tts.speak = spy
    _run(s, s._handle_final("ఈ రోజు చాలా కష్టంగా ఉంది", 0.0))
    assert len(seen) >= 2  # StubLLM streams two sentences
    assert set(seen) == {("te-IN", "V_TE")}


def test_fixed_lines_use_the_active_language_voice():
    mem = Memory(":memory:")
    mem.save_summary("h1", "old", "loop", "te")
    s = _te_session(StubLLM(), mem, caller="h1")
    s.user = mem.get_user("h1")
    mem.start_call(s.call_id, "h1")
    _run(s, s._handle_final("మర్చిపో", 0.0))
    assert s.tts.calls == [(TE.forgot, "te-IN", "V_TE")]
    s2 = _te_session(StubLLM(), None)
    _run(s2, s2._opening())
    assert {(c[1], c[2]) for c in s2.tts.calls} == {("te-IN", "V_TE")}
    s3 = _session(StubLLM(), None, caller=None)
    s3.state.language = "en"
    _run(s3, s3._handle_final("will you keep this secret?", 0.0))
    assert s3.tts.calls == [(EN.secrecy_no_memory, "en-IN", "V_EN")]
