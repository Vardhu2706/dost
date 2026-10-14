"""Split a streaming LLM reply into speakable sentences, flushing the first early."""

from __future__ import annotations

from collections.abc import AsyncIterator

_END = "।.?!"
_SOFT = ",;—"
_FIRST_SOFT_MIN = 28  # chars before the first chunk may break at a comma


def _split_point(buf: str, first: bool) -> int:
    """Index just past the first complete chunk in buf, or -1."""
    for i, ch in enumerate(buf):
        if ch in _END:
            # a '.' inside a number/abbreviation has no whitespace after it
            if ch == "." and i + 1 < len(buf) and not buf[i + 1].isspace():
                continue
            if i + 1 == len(buf) and ch == ".":
                continue  # may be "..." or a decimal still arriving
            j = i + 1
            while j < len(buf) and buf[j] in _END:
                j += 1
            return j
        if first and ch in _SOFT and i >= _FIRST_SOFT_MIN and i + 1 < len(buf):
            return i + 1
    return -1


async def sentences(tokens: AsyncIterator[str]) -> AsyncIterator[str]:
    buf = ""
    first = True
    async for tok in tokens:
        buf += tok
        while (cut := _split_point(buf, first)) != -1:
            out, buf = buf[:cut].strip(), buf[cut:]
            if out:
                first = False
                yield out
    if buf.strip():
        yield buf.strip()
