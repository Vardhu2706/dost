import asyncio

from dost.brain.chunker import sentences


async def _collect(parts: list[str]) -> list[str]:
    async def gen():
        for p in parts:
            yield p

    return [s async for s in sentences(gen())]


def test_splits_on_danda_and_question():
    out = asyncio.run(_collect(["अरे यार", "। क्या हुआ", "? बताओ", "।"]))
    assert out == ["अरे यार।", "क्या हुआ?", "बताओ।"]


def test_decimal_not_split():
    out = asyncio.run(_collect(["It costs 3.5 rupees. ok"]))
    assert out == ["It costs 3.5 rupees.", "ok"]


def test_first_chunk_flushes_at_comma():
    out = asyncio.run(_collect(["Haan yaar main sun raha hoon bilkul, ", "bata kya hua."]))
    assert out == ["Haan yaar main sun raha hoon bilkul,", "bata kya hua."]


def test_trailing_text_without_punctuation():
    assert asyncio.run(_collect(["बस"])) == ["बस"]
