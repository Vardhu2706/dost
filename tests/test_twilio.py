import asyncio
import base64
import json
import math

from dost.audio.pcm import Downsample3x, Upsample2x, mulaw_to_pcm16, pcm16_to_mulaw
from dost.audio.twilio import (
    TwilioAdapter,
    caller_hash,
    media_token,
    twilio_signature,
    valid_signature,
    voice_twiml,
)
import array


def _tone(n: int, rate: int, hz: float = 440, amp: int = 12000) -> bytes:
    return array.array("h", (int(amp * math.sin(2 * math.pi * hz * i / rate)) for i in range(n))).tobytes()


def test_mulaw_roundtrip_is_close():
    pcm = _tone(800, 8000)
    back = array.array("h")
    back.frombytes(mulaw_to_pcm16(pcm16_to_mulaw(pcm)))
    orig = array.array("h")
    orig.frombytes(pcm)
    assert len(back) == len(orig)
    # mu-law is ~13-bit companded: error stays within a few percent of full scale
    assert max(abs(a - b) for a, b in zip(orig, back)) < 700
    assert mulaw_to_pcm16(bytes([0xFF])) == b"\x00\x00"  # mu-law silence


def test_resamplers_have_expected_lengths_across_chunks():
    up = Upsample2x()
    assert len(up.process(_tone(160, 8000))) == 160 * 2 * 2  # 20 ms 8k -> 640 bytes at 16k
    down = Downsample3x()
    out = down.process(_tone(481, 24000)) + down.process(_tone(479, 24000))
    assert len(out) // 2 == 960 // 3


def test_signature_roundtrip_and_tamper():
    url, params = "https://x.example/twilio/voice", {"CallSid": "CA1", "From": "+911234567890"}
    sig = twilio_signature(url, params, "tok")
    assert valid_signature(url, params, sig, "tok")
    assert not valid_signature(url, {**params, "From": "+910000000000"}, sig, "tok")
    assert not valid_signature(url, params, None, "tok")


def test_hash_never_contains_number_and_is_keyed():
    h = caller_hash("+911234567890", "secret")
    assert "1234567890" not in h and len(h) == 64
    assert h != caller_hash("+911234567890", "other")
    assert media_token("CA1", "s") != media_token("CA2", "s")


def test_twiml_escapes_and_carries_parameters():
    x = voice_twiml("wss://h/twilio/media", {"token": 'a"b'})
    assert "<Connect><Stream" in x and 'name="token"' in x and "&quot;" in x or "'a\"b'" in x


class FakeWS:
    def __init__(self, incoming):
        self.incoming, self.sent, self.closed = list(incoming), [], False

    async def receive_text(self):
        return self.incoming.pop(0)

    async def send_text(self, t):
        self.sent.append(json.loads(t))

    async def close(self):
        self.closed = True


def test_adapter_inbound_outbound_and_clear():
    payload = base64.b64encode(bytes([0xFF]) * 160).decode()
    ws = FakeWS([
        json.dumps({"event": "media", "media": {"track": "inbound", "payload": payload}}),
        json.dumps({"event": "media", "media": {"track": "outbound", "payload": payload}}),
        json.dumps({"event": "stop"}),
    ])
    a = TwilioAdapter(ws, "MZ1")

    async def go():
        frames = [f async for f in a.frames()]
        assert len(frames) == 1 and len(frames[0]) == 640  # 20 ms of 16 kHz PCM16
        await a.send(_tone(1000, 24000))  # 1000 samples -> 333 mulaw bytes -> 2 full frames queued
        await a.flush()
        await a.clear_output()

    asyncio.run(go())
    media = [m for m in ws.sent if m["event"] == "media"]
    assert len(media) == 3 and all(m["streamSid"] == "MZ1" for m in media)
    assert all(len(base64.b64decode(m["media"]["payload"])) == 160 for m in media)
    assert ws.sent[-1] == {"event": "clear", "streamSid": "MZ1"}
