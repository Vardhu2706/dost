"""Detects feminine first-person forms. Dost's voices are male; the persona is masculine.

Used by evals/tests (not at runtime). Hindi marks gender on first-person verbs; Telugu first-person
verbs do not, so for Telugu we only catch self-description as a woman/girl (needs native review).
"""

from __future__ import annotations

import re

# Python's \b is unreliable next to Devanagari matras (they are not \w), so use explicit bounds.
_S = r"(?<![\w\u0900-\u097F])"
_E = r"(?![\w\u0900-\u097F])"
_FEMININE = [
    # Hindi progressive / habitual / ability / desire, first person
    rf"रही\s*(हूँ|हूं|हु){_E}",
    rf"ती\s*(हूँ|हूं|हु){_E}",  # करती हूँ, सुनती हूँ, चाहती हूँ, सकती हूँ
    rf"{_S}मैं{_S}?[^।?!.]{{0,30}}?{_S}(गई|गयी|आई|थी|देखी|सुनी|समझी){_E}",
    rf"{_S}मुझे[^।?!.]{{0,20}}?{_S}हुई{_E}",
    # Telugu: self-description as a woman/girl
    r"నేను\s+(ఒక\s+)?(అమ్మాయి|స్త్రీ|ఆడ)",
    r"(అమ్మాయిని|స్త్రీని)",
    # Romanized Hindi (should not appear, but catch it)
    r"\bmain\b[^.?!]{0,25}\b(rahi|karti|sakti|chahti|gayi|gai|aayi|thi)\b",
]
_RE = [re.compile(p, re.I) for p in _FEMININE]


def feminine_forms(text: str) -> list[str]:
    """Return the matched feminine first-person fragments (empty list = clean)."""
    return [m.group(0) for r in _RE for m in r.finditer(text)]
