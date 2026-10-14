"""PCM16 helpers. The orchestrator only ever sees 16 kHz mono PCM16 frames."""

from __future__ import annotations

STT_RATE = 16000
FRAME_MS = 20
FRAME_BYTES = STT_RATE * FRAME_MS // 1000 * 2  # 640


def bytes_to_ms(n: int, rate: int) -> float:
    return n / 2 / rate * 1000


# --- G.711 mu-law (pure Python; stdlib audioop is gone in 3.13) -------------------------------
import array
import sys


def _mulaw_decode_byte(u: int) -> int:
    u = ~u & 0xFF
    t = (((u & 0x0F) << 3) + 0x84) << ((u & 0x70) >> 4)
    return 0x84 - t if u & 0x80 else t - 0x84


_DECODE = [_mulaw_decode_byte(i) for i in range(256)]


def _mulaw_encode_sample(s: int) -> int:
    sign = 0x80 if s < 0 else 0
    s = min(-s if s < 0 else s, 32635) + 0x84
    exp = max(s.bit_length() - 8, 0)
    exp = min(exp, 7)
    mant = (s >> (exp + 3)) & 0x0F
    return ~(sign | (exp << 4) | mant) & 0xFF


def _i16(data: bytes) -> array.array:
    a = array.array("h")
    a.frombytes(data)
    if sys.byteorder == "big":
        a.byteswap()
    return a


def _to_bytes(a: array.array) -> bytes:
    if sys.byteorder == "big":
        a.byteswap()
    return a.tobytes()


def mulaw_to_pcm16(data: bytes) -> bytes:
    return _to_bytes(array.array("h", (_DECODE[b] for b in data)))


def pcm16_to_mulaw(data: bytes) -> bytes:
    return bytes(_mulaw_encode_sample(s) for s in _i16(data))


class Upsample2x:
    """8 kHz -> 16 kHz PCM16 by linear interpolation; keeps one sample of state across frames."""

    def __init__(self) -> None:
        self._prev = 0

    def process(self, data: bytes) -> bytes:
        out = array.array("h")
        prev = self._prev
        for x in _i16(data):
            out.append((prev + x) // 2)
            out.append(x)
            prev = x
        self._prev = prev
        return _to_bytes(out)


class Downsample3x:
    """24 kHz -> 8 kHz PCM16 by averaging triplets; carries leftover samples across chunks."""

    def __init__(self) -> None:
        self._rest = array.array("h")

    def process(self, data: bytes) -> bytes:
        buf = self._rest + _i16(data[: len(data) // 2 * 2])
        n = len(buf) // 3 * 3
        self._rest = buf[n:]
        out = array.array("h", ((buf[i] + buf[i + 1] + buf[i + 2]) // 3 for i in range(0, n, 3)))
        return _to_bytes(out)
