"""Rule-based crisis screen (Telugu stems: needs native review) and per-call risk persistence.

Patterns are matched against normalized text (NFC, no nukta, punctuation removed). Hits only
ever *raise* risk; the analyzer can raise it further. Nothing here stores or logs content.
"""

from __future__ import annotations

import unicodedata
from enum import IntEnum


class Risk(IntEnum):
    NONE = 0
    LOW = 1
    ELEVATED = 2
    HIGH = 3

    @classmethod
    def parse(cls, value: object) -> Risk:
        try:
            return cls[str(value).strip().upper()]
        except KeyError:
            return cls.NONE


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFC", text).casefold()
    text = text.replace("़", "").replace("ँ", "ं")  # nukta, chandrabindu -> anusvara
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        out.append(" " if cat[0] in "PSZC" else ch)
    return " ".join("".join(out).split())


# (risk, category, stems). Stems are substrings of the normalized transcript.
_RAW: list[tuple[Risk, str, tuple[str, ...]]] = [
    (Risk.HIGH, "self_harm", (
        # English / Hinglish
        "want to die", "wanna die", "kill myself", "end my life", "end it all", "suicide", "suicidal",
        "marna chah", "mar jana chah", "mar jaana chah", "mar jaun", "mar jau", "mar jaoon",
        "jaan de d", "jaan de du", "khudkushi", "khud khushi", "aatmahatya", "atmahatya",
        "jeena nahi", "jina nahi", "jeene ka mann nahi", "jeene ka man nahi", "jeene ki ichha nahi",
        "zindagi khatam", "sab khatam kar", "khud ko khatam", "khud ko hurt", "khud ko nuksan",
        "apne aap ko khatam", "khud ko maar",
        # passive ideation (Hinglish)
        "jeene ka dil nahi", "jeene ka mood nahi", "jeene ki wajah nahi", "jeene ka koi matlab nahi",
        "jeene ka koi fayda nahi", "jee kar kya karunga", "jeekar kya karunga", "jee ke kya karunga",
        "zinda nahi reh", "zinda nahi rah", "zinda rehna nahi", "nahi rehna chah", "nahi rahna chah",
        "kaash main mar", "kaash mar", "mar hi jaun", "mar hi jau", "mar jata to", "mar jaata to",
        "duniya se chala jaun", "duniya chhod", "sab khatam kar", "khatam ho jaun", "khatam kar dun",
        "main nahi rahunga", "mere na rehne", "jee nahi sakta", "jee nahi paa", "ji nahi paa",
        # Devanagari
        "मरना चाह", "मर जाना चाह", "मर जाऊं", "मर जाउं", "मर जाउंगा", "जान दे", "जीना नही",
        "जीने का मन नही", "जीने की इच्छा नही", "खुदकुशी", "आत्महत्या", "जिंदगी खत्म", "सब खत्म कर",
        "खुद को खत्म", "खुद को मार", "खुद को नुकसान", "खुद को चोट",
        # passive ideation (Devanagari)
        "जीने का दिल नही", "जीने की वजह नही", "जीने का कोई मतलब नही", "जीने का कोई फायदा नही",
        "जी कर क्या करू", "जीकर क्या करू", "जी के क्या करू", "जिंदा नही रह", "जिंदा रहना नही",
        "नही रहना चाह", "नही जीना", "काश मैं मर", "काश मर", "मर ही जाऊं", "मर जाता तो", "मर जाती तो",
        "दुनिया से चला जाऊं", "दुनिया छोड़", "सब खत्म कर", "खत्म हो जाऊं", "खत्म कर दू", "खत्म कर दूं",
        "मैं नही रहूंगा", "मैं नही रहूंगी", "मेरे ना रहने", "जी नही सकता", "जी नही सकती", "जी नही पा",
        # Telugu script (NEEDS NATIVE REVIEW)
        "చనిపోవాల", "చచ్చిపోవాల", "చావాల", "ఆత్మహత్య", "బతకాలని లేద", "బ్రతకాలని లేద",
        "జీవించాలని లేద", "చంపుకో",
        # passive ideation (Telugu script) (NEEDS NATIVE REVIEW)
        "బతకాలనిపించ", "బ్రతకాలనిపించ", "బతకడం ఇష్టం లేదు", "బ్రతకడం ఇష్టం లేదు", "ఈ జీవితం వద్దు",
        "జీవితం వద్దు", "చచ్చిపోతా", "చనిపోతా", "చచ్చిపోయి", "నేను లేకపోతే బాగుండు", "బతకడం వద్దు",
        "బతికి ఏం చేయాలి", "బతికి ఏమి చేయాలి",
        # Telugu romanized (NEEDS NATIVE REVIEW)
        "chanipovali", "chanipovaali", "chachipovali", "chachipovaali", "chavalani",
        "bathakalani ledu", "bratakalani ledu", "bathakalani anipinchatledu",
        "bathakalani anipinchatle", "bratakalani anipinchatle", "bathakalanipinchatle",
        "bathakadam ishtam ledu", "bratakadam ishtam ledu", "ee jeevitham vaddu", "jeevitham vaddu",
        "nenu chanipotha", "nenu chachipotha", "chanipotha", "chachipotha", "chanipovalani",
        "chachipovalani", "nenu lekapote bagundu", "bathikina em chestha",
    )),
    (Risk.HIGH, "medical_emergency", (
        "heart attack", "overdose", "zehar kha", "pills kha li", "behosh", "saans nahi le pa",
        "दिल का दौरा", "सांस नही ले", "ओवरडोज", "जहर खा", "गोलियां खा", "बेहोश", "खून बह",
    )),
    (Risk.ELEVATED, "hopelessness", (
        "hopeless", "no point", "koi umeed nahi", "kuch faayda nahi", "koi fayda nahi",
        "sab bekar", "zindagi se thak", "bojh hoon", "bojh hun", "burden",
        "कोई उम्मीद नही", "कुछ फायदा नही", "कोई फायदा नही", "सब बेकार", "जिंदगी से थक",
        "बोझ हूं", "बोझ हु",
    )),
    (Risk.ELEVATED, "violence_abuse", (
        "maarta hai", "marta hai", "maarti hai", "peetta", "pitai", "hits me", "beats me", "abuse",
        "मारता है", "मारती है", "पीटता", "पीटती", "हाथ उठाया", "मारपीट",
    )),
]
_PATTERNS = [(r, c, tuple(normalize(s) for s in stems)) for r, c, stems in _RAW]


# A film, song or joke marker next to a self-harm phrase may mean it is a quote. We never ignore
# the hit: it drops from HIGH to ELEVATED (gentle check-in) and the analyzer decides the rest.
_QUOTE_MARKERS = tuple(
    normalize(m)
    for m in (
        "film", "movie", "picture", "song", "gaana", "gana", "gaane", "lyrics", "dialogue", "dialog",
        "serial", "series", "show", "kahani", "story", "novel", "book", "poem", "kavita", "shayari",
        "joke", "mazak", "mazaak", "meme", "reel",
        "फिल्म", "मूवी", "गाना", "गाने", "गीत", "डायलॉग", "सीरियल", "कहानी", "किताब", "कविता", "शायरी",
        "मज़ाक", "मजाक", "जोक", "सिनेमा",
        "సినిమా", "పాట", "జోక్", "కథ", "డైలాగ్",
    )
)


def _has_quote_marker(norm: str) -> bool:
    words = f" {norm} "
    for m in _QUOTE_MARKERS:
        if m.isascii():
            if f" {m} " in words or f" {m}s " in words:
                return True
        elif m in norm:
            return True
    return False


def screen(text: str) -> tuple[Risk, list[str]]:
    """Return (risk, matched categories). Risk is NONE when nothing matches."""
    norm = normalize(text)
    level = Risk.NONE
    cats: list[str] = []
    for risk, cat, stems in _PATTERNS:
        if any(s in norm for s in stems):
            if cat == "self_harm" and risk == Risk.HIGH and _has_quote_marker(norm):
                risk, cat = Risk.ELEVATED, "self_harm_quoted_context"
            level = max(level, risk)
            if cat not in cats:
                cats.append(cat)
    return level, cats


class RiskTracker:
    """Within a call risk rises immediately but falls at most one level per turn."""

    def __init__(self) -> None:
        self.level = Risk.NONE
        self.max_level = Risk.NONE

    def update(self, observed: Risk) -> Risk:
        self.level = max(observed, Risk(max(self.level - 1, 0)))
        self.max_level = max(self.max_level, self.level)
        return self.level
