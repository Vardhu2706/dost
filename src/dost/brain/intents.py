"""Deterministic caller intents: forget-me, secrecy question, language request, language tracking.

Rule based on purpose: these trigger fixed behavior (deleting data, a fixed line), so they must be
predictable. Telugu stems need native review.
"""

from __future__ import annotations

from dataclasses import dataclass

from dost.brain.safety import normalize

# Contiguous token sequences. Short utterances only (a command, not a story).
_FORGET = [
    ("bhool", "jao"), ("bhul", "jao"), ("bhool", "jaiye"), ("bhula", "do"),
    ("भूल", "जाओ"), ("भूल", "जाइए"), ("भुला", "दो"),
    ("forget", "me"), ("forget", "it"), ("forget", "everything"), ("forget", "all"),
    ("delete", "my", "data"), ("delete", "everything"),
    # Telugu (needs native review): "మర్చిపో/మరచిపో" imperative, matched as whole tokens so that
    # "మర్చిపోయాను" ("I forgot") does not trigger.
    ("మర్చిపో",), ("మరచిపో",), ("మర్చిపోండి",), ("మరచిపోండి",),
    ("marchipo",), ("marchipondi",), ("marchipovali",),
]
_FORGET_MAX_WORDS = 8
# "usse bhool jao" = forget *him/her*; not a request to delete the caller's data.
_OTHER_OBJECT = {"usse", "use", "usko", "unhe", "unko", "isse", "ise", "उसे", "उसको", "उन्हें", "इसे",
                 "him", "her", "them", "అతన్ని", "ఆమెను"}
_SELF_OBJECT = {"mujhe", "meri", "mera", "sab", "sabkuch", "मुझे", "मेरी", "मेरा", "सब", "सबकुछ", "me"}

_SECRECY = (
    "secret rakh", "secret rahega", "secret rakhoge", "keep this secret", "keep it secret",
    "keep a secret", "keep my secret", "keep this between", "tell anyone", "tell anybody",
    "kisi ko mat bata", "kisi ko nahi bata", "kisi ko na bata", "kisi ko bataoge", "kisi ko bata doge",
    "promise karo", "promise kar", "vaada karo", "vada karo", "raaz rakh", "raz rakh",
    "वादा करो", "किसी को मत बता", "किसी को नहीं बता", "किसी को न बता", "किसी को बताओगे",
    "किसी को बता दोगे", "राज रख", "राज ही रख", "सीक्रेट रख", "सीक्रेट रहेगा",
    # Telugu (needs native review)
    "రహస్యం", "ఎవరికీ చెప్పొద్దు", "ఎవరికీ చెప్పకు", "ఎవరికీ చెప్పవు కదా", "rahasyam",
    "evariki cheppaku", "evarikee cheppoddu", "evariki cheppoddu",
)

_LANG_STEMS: dict[str, tuple[str, ...]] = {
    "en": ("english mein", "english me", "in english", "speak english", "english lo", "english bol",
           "इंग्लिश में", "अंग्रेजी में", "अंग्रेज़ी में", "ఇంగ్లీష్ లో", "ఇంగ్లీషులో", "ఇంగ్లీష్‌లో"),
    "hi": ("hindi mein", "hindi me", "in hindi", "speak hindi", "hindi bol", "hindi lo",
           "हिंदी में", "हिन्दी में", "హిందీలో", "హిందీ లో"),
    "te": ("telugu mein", "telugu me", "telugu lo", "in telugu", "speak telugu", "telugu bol",
           "तेलुगु में", "तेलुगू में", "తెలుగులో", "తెలుగు లో"),
}
_REQUEST_VERBS = (
    "bol", "baat", "speak", "talk", "matlad", "बोल", "बात", "మాట్లాడ", "చెప్ప",
    "please", "plz", "can you", "could you", "kya aap", "kya tum",
)


def _contains_seq(tokens: list[str], seq: tuple[str, ...]) -> int:
    n = len(seq)
    for i in range(len(tokens) - n + 1):
        if tuple(tokens[i : i + n]) == seq:
            return i
    return -1


def forget_me(text: str) -> bool:
    tokens = normalize(text).split()
    if not tokens or len(tokens) > _FORGET_MAX_WORDS:
        return False
    for seq in _FORGET:
        i = _contains_seq(tokens, seq)
        if i < 0:
            continue
        before = tokens[i - 1] if i > 0 else ""
        if before in _OTHER_OBJECT and before not in _SELF_OBJECT:
            continue
        return True
    return False


def secrecy_question(text: str) -> bool:
    norm = normalize(text)
    return any(normalize(s) in norm for s in _SECRECY)


def requested_language(text: str) -> str | None:
    norm = normalize(text)
    if not any(v in norm for v in _REQUEST_VERBS):
        return None
    hits = {lang for lang, stems in _LANG_STEMS.items() if any(normalize(s) in norm for s in stems)}
    return hits.pop() if len(hits) == 1 else None


_CODE = {"hi-IN": "hi", "te-IN": "te", "en-IN": "en", "en-US": "en", "en-GB": "en"}
MIN_LANG_CONFIDENCE = 0.5
DWELL_TURNS = 3  # caller turns after a switch during which no automatic switch can happen


@dataclass
class LangTracker:
    """Switch only after two consecutive confident finals in another language (or on request).

    After any switch there is a dwell: the next DWELL_TURNS caller turns cannot trigger an automatic
    switch (an explicit request still can), so a few misdetected short finals cannot flip the voice.
    """

    current: str = "hi"
    _pending: str | None = None
    _count: int = 0
    _since_switch: int = DWELL_TURNS + 1  # no dwell at the start of a call

    def request(self, lang: str) -> bool:
        changed = lang != self.current
        self.current, self._pending, self._count = lang, None, 0
        if changed:
            self._since_switch = 0
        return changed

    def observe(self, detected: str | None, confidence: float | None) -> bool:
        """Feed one final's detected language. Returns True if the call language changed."""
        self._since_switch += 1
        lang = _CODE.get(detected or "")
        if self._since_switch <= DWELL_TURNS:
            self._pending, self._count = None, 0
            return False  # dwelling after a switch
        if lang is None or (confidence is not None and confidence < MIN_LANG_CONFIDENCE):
            return False  # unknown or unsure: neither counts for nor against a switch
        if lang == self.current:
            self._pending, self._count = None, 0
            return False
        if lang == self._pending:
            self._count += 1
        else:
            self._pending, self._count = lang, 1
        if self._count >= 2:
            self.current, self._pending, self._count = lang, None, 0
            self._since_switch = 0
            return True
        return False
