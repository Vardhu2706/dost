"""Per-call orchestrator: STT -> (intents | rule screen | analyzer | reply LLM) -> chunker -> TTS."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

from dost.audio.browser import AudioAdapter
from dost.brain import intents, safety
from dost.brain.analyzer import TIMEOUT_S, Analysis, analyze
from dost.brain.chunker import sentences
from dost.brain.lines import TTS_LANG, Lines, lines_for
from dost.brain.phases import CallState, next_phase
from dost.brain.prompts import LANGUAGE_RULES, OPEN_LOOP_OPENER
from dost.brain.reply import build_messages, safety_question
from dost.brain.safety import Risk, RiskTracker
from dost.config import Settings
from dost.memory.db import Memory
from dost.memory.models import UserRecord
from dost.memory.summarizer import fallback_summary, summarize
from dost.sarvam.llm import SarvamLLM
from dost.sarvam.stt import Final, Partial, SarvamSTT, SpeechStart
from dost.sarvam.tts import SarvamTTS

log = logging.getLogger("dost.session")

_LANG_FROM_CODE = {"hi-IN": "hi", "te-IN": "te", "en-IN": "en"}
# language -> (Settings attribute, env variable it comes from)
_VOICE_SETTING = {
    "hi": ("voice_hi", "VOICE_HI"),
    "te": ("voice_te", "VOICE_TE"),
    "en": ("voice_en", "VOICE_EN"),
}


@dataclass(frozen=True)
class Voice:
    """One voice + language code, chosen once and used for every chunk of a reply."""

    lang: str  # hi | te | en
    voice: str
    code: str  # TTS language_code, e.g. te-IN
    source: str  # the env variable the voice came from


@dataclass
class TurnTimings:
    t_final: float
    llm_first_token: float | None = None
    tts_first_chunk: float | None = None

    def line(self) -> str:
        def d(v: float | None) -> str:
            return "-" if v is None else f"{v - self.t_final:.2f}s"

        return f"timings: llm_first_token={d(self.llm_first_token)} first_audio={d(self.tts_first_chunk)}"


@dataclass
class Session:
    settings: Settings
    adapter: AudioAdapter
    stt: SarvamSTT
    tts: SarvamTTS
    llm: SarvamLLM
    lang: str = ""  # unused; kept so old callers keep working (language lives in state.language)
    caller_hash: str | None = None  # HMAC of the caller's number: the memory key. None = no memory
    memory: Memory | None = None
    call_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    history: list[dict] = field(default_factory=list)
    state: CallState = field(default_factory=CallState)
    risk: RiskTracker = field(default_factory=RiskTracker)
    started: float = field(default_factory=time.monotonic)
    last_activity: float = field(default_factory=time.monotonic)
    crisis_turns: int = 0  # replies given in crisis mode this call
    user: UserRecord | None = None
    forgotten: bool = False  # caller asked to be forgotten: nothing more is stored this call
    _number_said: bool = False
    _turn: asyncio.Task | None = None
    _speaking: bool = False
    _tracker: intents.LangTracker = field(default_factory=intents.LangTracker)
    _turn_idx: int = 0
    _cur: Voice | None = None  # voice chosen at the start of the current turn

    # --- derived ------------------------------------------------------------

    @property
    def memory_active(self) -> bool:
        return self.memory is not None and self.caller_hash is not None and not self.forgotten

    @property
    def L(self) -> Lines:
        return lines_for(self.state.language)

    def _voice(self) -> str:
        return self._voice_for(self.state.language).voice

    def _tts_lang(self) -> str:
        return self._voice_for(self.state.language).code

    def _voice_for(self, lang: str) -> Voice:
        lang = lang if lang in _VOICE_SETTING else "hi"
        attr, var = _VOICE_SETTING[lang]
        return Voice(lang, getattr(self.settings, attr), TTS_LANG[lang], var)

    def _pick_voice(self, purpose: str) -> Voice:
        """The one voice for this reply/line, from the active language, logged with its source."""
        v = self._voice_for(self.state.language)
        log.info(
            "voice pick call=%s turn=%d purpose=%s lang=%s voice=%s code=%s from=%s",
            self.call_id, self.state.user_turns, purpose, v.lang, v.voice, v.code, v.source,
        )
        return v

    # --- lifecycle ----------------------------------------------------------

    async def run(self) -> None:
        if self.memory_active:
            self.user = self.memory.get_user(self.caller_hash)
            self.memory.start_call(self.call_id, self.caller_hash)
            if self.user:
                self.state.summary = self.user.summary
                self.state.open_loop = self.user.open_loop
                self.state.language = self.user.language_pref or self.state.language
        else:
            self.state.language = _LANG_FROM_CODE.get(self.settings.default_lang, "hi")
        self._tracker.current = self.state.language
        await self._start_turn(self._opening())
        try:
            async for ev in self.stt.stream(self.adapter.frames()):
                if isinstance(ev, SpeechStart) or (isinstance(ev, Partial) and ev.text.strip()):
                    self.last_activity = time.monotonic()
                    await self._maybe_barge_in()
                elif isinstance(ev, Final) and ev.text.strip():
                    self.last_activity = time.monotonic()
                    log.info("final [%s %s] chars=%d", ev.lang, ev.confidence, len(ev.text))
                    await self._cancel_turn()
                    self._update_language(ev)
                    await self._start_turn(self._handle_final(ev.text, time.monotonic()))
        finally:
            await self._cancel_turn()
            log.info("call %s max_risk=%s phase=%s", self.call_id, self.risk.max_level.name, self.state.phase)
            try:
                await self._finish()
            except Exception:
                log.exception("post-call memory step failed")
            await self.llm.aclose()
            await self.adapter.close()

    async def _finish(self) -> None:
        """Close the call row and, if memory is on, fold the call into the caller's summary."""
        if self.memory is None or self.caller_hash is None or self.forgotten:
            return
        mem = self.memory
        mem.end_call(self.call_id, self.state.phase, self.risk.max_level.name.lower())
        if self.state.user_turns == 0:
            mem.delete_transcript(self.call_id)
            return
        # Calls whose summary failed earlier are folded in first (oldest first), then this one.
        prev = self.user.summary if self.user else ""
        loop: str | None = self.user.open_loop if self.user else None
        for cid in [*mem.pending_calls(self.caller_hash, exclude=self.call_id), self.call_id]:
            turns = mem.transcript(cid)
            if not turns:
                continue
            current = cid == self.call_id
            result = await summarize(
                self.llm, prev, turns, self.state.facts if current else [], self.state.open_loop if current else None
            )
            prev, loop = result.summary, result.open_loop
            mem.delete_transcript(cid)  # the summary is all that is kept
        mem.save_summary(self.caller_hash, prev, loop, self.state.language)

    # --- language -----------------------------------------------------------

    def _update_language(self, ev: Final) -> None:
        req = intents.requested_language(ev.text)
        changed = self._tracker.request(req) if req else self._tracker.observe(ev.lang, ev.confidence)
        if changed:
            log.info("language switch %s -> %s", self.state.language, self._tracker.current)
            self.state.language = self._tracker.current
            if self.state.language != "hi":
                self.state.address = "tum"  # address forms are a Hindi notion; reset

    # --- turn control -------------------------------------------------------

    async def _start_turn(self, coro) -> None:
        self._turn = asyncio.create_task(coro)

    async def _cancel_turn(self) -> None:
        task, self._turn = self._turn, None
        if task and not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        await self.tts.cancel()

    async def _maybe_barge_in(self) -> None:
        if self._speaking:
            log.info("barge-in")
            await self._cancel_turn()
            await self.adapter.clear_output()
            self._speaking = False

    # --- persistence helpers --------------------------------------------------

    def _record(self, role: str, text: str) -> None:
        if self.memory_active and text.strip():
            self.memory.add_turn(self.call_id, self._turn_idx, role, text, self.state.language)
            self._turn_idx += 1

    def _risk_event(self, level: Risk) -> None:
        if self.memory_active:
            self.memory.add_risk_event(self.call_id, level.name.lower())

    # --- the opening ----------------------------------------------------------

    async def _opening(self) -> None:
        voice = self._cur = self._pick_voice("opener")
        L = lines_for(voice.lang)
        spoken: list[str] = []
        loop_task: asyncio.Task | None = None
        if self.memory_active and self.user and self.user.open_loop:
            loop_task = asyncio.create_task(self._open_loop_sentence())

        async def gen() -> AsyncIterator[str]:
            yield L.opener_a  # AI disclosure is always the first thing said
            if not self.memory_active:
                yield L.opener_q
            elif self.user is None:
                yield L.memory_first_call
                yield L.opener_q
            else:
                sentence = await loop_task if loop_task else None
                if sentence:
                    yield sentence
                else:
                    yield L.welcome_back
                    yield L.opener_q

        try:
            await self._speak(gen(), TurnTimings(time.monotonic()), spoken, voice, "opener")
        finally:
            if loop_task and not loop_task.done():
                loop_task.cancel()
            if spoken:
                text = " ".join(spoken)
                self.history.append({"role": "assistant", "content": text})
                self._record("assistant", text)

    async def _open_loop_sentence(self) -> str | None:
        """One natural sentence asking about the open loop the caller chose; None on any failure."""
        prompt = OPEN_LOOP_OPENER.format(
            language_rules=LANGUAGE_RULES.get(self.state.language, LANGUAGE_RULES["hi"]),
            summary=self.state.summary or "(none)",
            open_loop=self.state.open_loop,
        )
        try:
            text = await asyncio.wait_for(
                self.llm.complete([{"role": "system", "content": prompt}], max_tokens=120), timeout=4.0
            )
        except Exception as exc:
            log.warning("open-loop opener failed: %s", type(exc).__name__)
            return None
        text = " ".join(text.split())
        return text or None

    # --- the turn -----------------------------------------------------------

    async def _say_fixed(self, lines: list[str], purpose: str = "fixed") -> None:
        async def gen() -> AsyncIterator[str]:
            for line in lines:
                yield line

        await self._speak(gen(), TurnTimings(time.monotonic()), None, self._pick_voice(purpose), purpose)

    async def _handle_final(self, text: str, t_final: float) -> None:
        timings = TurnTimings(t_final)
        voice = self._cur = self._pick_voice("turn")  # one voice for everything said this turn
        self.history.append({"role": "user", "content": text})
        self._record("user", text)
        self.state.user_turns += 1

        rule_risk, cats = safety.screen(text)
        level = self._effective(self.risk.update(rule_risk))
        # Content-free: levels and categories only, never the transcript.
        log.info(
            "turn_risk call=%s turn=%d rule=%s cats=%s level=%s crisis_turns=%d lang=%s",
            self.call_id, self.state.user_turns, rule_risk.name, cats, level.name, self.crisis_turns,
            self.state.language,
        )
        if level >= Risk.ELEVATED:
            self._risk_event(level)

        # Fixed-behavior intents. Crisis always wins over the forget and secrecy shortcuts: if the
        # rule screen hit anything, the crisis path runs first and forget is handled next turn.
        spoken: list[str] = []
        if rule_risk == Risk.NONE and intents.forget_me(text):
            await self._forget(spoken, voice)
            if self.crisis_turns == 0 and level < Risk.HIGH:
                self._finish_turn_history(spoken, timings)
                return
        elif level < Risk.HIGH and self.crisis_turns == 0 and intents.secrecy_question(text):
            L = lines_for(voice.lang)
            line = L.secrecy if self.memory_active else L.secrecy_no_memory
            await self._say_fixed_tracked([line], spoken, voice, "secrecy")
            self._finish_turn_history(spoken, timings)
            return

        analysis_task = asyncio.create_task(self._analyze(text, rule_risk))
        reply_task: asyncio.Task | None = None
        try:
            if level >= Risk.HIGH:
                # Rule screen is enough: do not wait for the analyzer.
                await self._reply(Risk.HIGH, timings, spoken, gate=None)
            else:
                reply_task = asyncio.create_task(self._reply(level, timings, spoken, gate=analysis_task))
                await asyncio.wait({analysis_task})
                if self._effective(self.risk.level) >= Risk.HIGH:
                    # Escalated by the analyzer (possibly after audio started): switch to crisis mode.
                    log.info("escalation to crisis mode")
                    reply_task.cancel()
                    await asyncio.gather(reply_task, return_exceptions=True)
                    await self.tts.cancel()
                    await self.adapter.clear_output()
                    await self._reply(Risk.HIGH, timings, spoken, gate=None)
                else:
                    await reply_task
        finally:
            for t in (analysis_task, reply_task):
                if t and not t.done():
                    t.cancel()
            self._finish_turn_history(spoken, timings)

    def _finish_turn_history(self, spoken: list[str], timings: TurnTimings) -> None:
        if spoken:  # keep what was actually said, so barge-in truncates history
            said = " ".join(spoken)
            self.history.append({"role": "assistant", "content": said})
            self._record("assistant", said)
        log.info(timings.line())

    async def _say_fixed_tracked(
        self, lines: list[str], spoken: list[str], voice: Voice, purpose: str
    ) -> None:
        async def gen() -> AsyncIterator[str]:
            for line in lines:
                yield line

        await self._speak(gen(), TurnTimings(time.monotonic()), spoken, voice, purpose)

    async def _forget(self, spoken: list[str], voice: Voice) -> None:
        """Delete everything stored for this caller, then confirm aloud (fixed line)."""
        existed = False
        if self.memory is not None and self.caller_hash is not None:
            existed = self.memory.forget(self.caller_hash)
        was_active = self.memory_active
        self.forgotten = True  # nothing more is written this call, including the post-call summary
        self.state.summary, self.state.open_loop, self.state.facts = "", None, []
        log.info("forget-me call=%s deleted_record=%s", self.call_id, existed)
        L = lines_for(voice.lang)
        line = L.forgot if (existed or was_active) else L.forgot_nothing
        await self._say_fixed_tracked([line], spoken, voice, "forget")

    def _effective(self, level: Risk) -> Risk:
        """Once a crisis has started, stay in crisis mode while risk is still at least elevated."""
        if self.crisis_turns > 0 and level >= Risk.ELEVATED:
            return Risk.HIGH
        return level

    async def _analyze(self, text: str, rule_risk: Risk) -> Analysis | None:
        a = await analyze(self.llm, self.state, self.history[:-1], text)
        st = self.state
        if a is None:
            observed = rule_risk  # fall back to the rule screen only
            phase_hint = None
            wants_end = False
        else:
            observed = max(rule_risk, a.risk_level)
            phase_hint, wants_end = a.phase, a.wants_to_end
            # st.language is driven by the language tracker (finals + requests), not by the analyzer.
            st.formality = a.reg.formality
            if a.reg.address != "na" and st.language == "hi":
                st.address = a.reg.address
            st.emotion = a.emotion
            for fact in a.memory_facts:
                if fact and fact not in st.facts:
                    st.facts.append(fact)
            if a.open_loop:
                st.open_loop = a.open_loop
        # The reply task may already have applied the rule level; update() only drops one level/turn.
        level = Risk(max(observed, self.risk.level))
        self.risk.level = level
        self.risk.max_level = max(self.risk.max_level, level)
        log.info(
            "analysis call=%s analyzer_risk=%s level=%s phase=%s",
            self.call_id, a.risk_level.name if a else "unavailable", level.name, st.phase,
        )
        if a is not None and a.risk_level >= Risk.ELEVATED and rule_risk < a.risk_level:
            self._risk_event(a.risk_level)
        now = time.monotonic()
        st.phase = next_phase(
            st.phase, phase_hint, wants_end,
            elapsed_min=(now - self.started) / 60,
            soft_wind_down_min=self.settings.soft_wind_down_min,
        )
        if self._effective(level) >= Risk.HIGH:
            st.phase = "exploring" if st.phase in ("winding_down", "closing") else st.phase
        return a

    async def _reply(
        self,
        risk: Risk,
        timings: TurnTimings,
        spoken: list[str],
        gate: asyncio.Task | None,
    ) -> None:
        crisis = risk >= Risk.HIGH
        if crisis:
            self.crisis_turns += 1
        turn_no = self.crisis_turns
        messages = build_messages(self.state, self.history, risk, crisis_turn=turn_no)
        if crisis:
            self._risk_event(Risk.HIGH)
            log.info("risk_event call=%s ts=%.0f level=HIGH crisis_turn=%d", self.call_id, time.time(), turn_no)
        voice = self._cur or self._pick_voice("reply")
        L = lines_for(voice.lang)

        async def tokens() -> AsyncIterator[str]:
            async for tok in self.llm.stream(messages):
                if timings.llm_first_token is None:
                    timings.llm_first_token = time.monotonic()
                yield tok

        async def gated() -> AsyncIterator[str]:
            first = True
            try:
                if crisis and turn_no >= 2 and not self._number_said:
                    # Plainly and without waiting for a yes: the number is spoken before anything else.
                    self._number_said = True
                    log.info("fixed line call=%s purpose=telemanas voice=%s from=%s", self.call_id, voice.voice, voice.source)
                    yield L.telemanas
                stream = sentences(tokens())
                async for sent in stream:
                    if crisis and turn_no == 1:
                        # One acknowledging sentence from the model, then the fixed direct question.
                        yield sent
                        await stream.aclose()
                        log.info("fixed line call=%s purpose=safety_q voice=%s from=%s", self.call_id, voice.voice, voice.source)
                        yield safety_question(voice.lang)
                        return
                    if first and gate is not None:
                        first = False
                        try:  # hold the first sentence until the analyzer returns (or 700 ms)
                            await asyncio.wait_for(asyncio.shield(gate), TIMEOUT_S)
                        except Exception:  # timeout or analyzer error: rule screen only
                            pass
                        if self._effective(self.risk.level) >= Risk.HIGH:
                            return  # the turn will switch to crisis mode
                    yield sent
            except asyncio.CancelledError:
                raise
            except Exception:
                if risk >= Risk.HIGH:
                    log.exception("crisis reply failed; using fixed fallback")
                    log.info("fixed line call=%s purpose=crisis_fallback voice=%s from=%s", self.call_id, voice.voice, voice.source)
                    for line in L.crisis_fallback_followup if turn_no >= 2 else L.crisis_fallback:
                        yield line
                else:
                    raise

        await self._speak(gated(), timings, spoken, voice, "reply")

    async def _speak(
        self,
        sents: AsyncIterator[str],
        timings: TurnTimings,
        spoken: list[str] | None,
        voice: Voice,
        purpose: str = "reply",
    ) -> None:
        """Speak every chunk with the SAME voice and language code (chosen once by the caller)."""
        self._speaking = True
        used: set[tuple[str, str]] = set()
        n = 0
        try:
            async for sent in sents:
                n += 1
                used.add((voice.voice, voice.code))
                log.info(
                    "tts chunk call=%s turn=%d purpose=%s n=%d voice=%s code=%s from=%s chars=%d",
                    self.call_id, self.state.user_turns, purpose, n, voice.voice, voice.code,
                    voice.source, len(sent),
                )
                if spoken is not None:
                    spoken.append(sent)
                async for chunk in self.tts.speak(sent, voice.code, voice.voice):
                    if timings.tts_first_chunk is None:
                        timings.tts_first_chunk = time.monotonic()
                    await self.adapter.send(chunk)
            flush = getattr(self.adapter, "flush", None)  # phone leg: send the sub-20 ms tail
            if flush is not None:
                await flush()
        finally:
            self._speaking = False
            if len(used) > 1:
                log.warning("VOICE MIX call=%s purpose=%s voices=%s", self.call_id, purpose, sorted(used))
            if n and self.state.language != voice.lang:
                log.warning(
                    "language changed during speech call=%s purpose=%s spoke=%s now=%s",
                    self.call_id, purpose, voice.lang, self.state.language,
                )
