import json

import pytest
from fastapi.testclient import TestClient

from dost.audio.twilio import media_token, twilio_signature


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "x")
    monkeypatch.setenv("SERVER_SECRET", "s3cret")
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://dost.example")
    from dost.main import app

    return TestClient(app)


def test_voice_rejects_bad_signature(client):
    r = client.post("/twilio/voice", data={"CallSid": "CA1", "From": "+911"}, headers={"X-Twilio-Signature": "bad"})
    assert r.status_code == 403


def test_voice_returns_twiml_without_raw_number(client):
    form = {"CallSid": "CA1", "From": "+919876543210"}
    sig = twilio_signature("https://dost.example/twilio/voice", form, "tok")
    r = client.post("/twilio/voice", data=form, headers={"X-Twilio-Signature": sig})
    assert r.status_code == 200
    assert "wss://dost.example/twilio/media" in r.text
    assert "9876543210" not in r.text
    assert f'value="{media_token("CA1", "s3cret")}"' in r.text


def test_media_socket_rejects_wrong_token(client):
    with client.websocket_connect("/twilio/media") as ws:
        ws.send_text(json.dumps({"event": "connected"}))
        ws.send_text(json.dumps({"event": "start", "start": {"streamSid": "MZ", "customParameters": {"call_sid": "CA1", "token": "nope"}}}))
        with pytest.raises(Exception):
            ws.receive_text()


def test_call_me_requires_secret_and_rate_limits(client, monkeypatch):
    import dost.main as m
    from dost.phone import RateLimiter

    monkeypatch.setenv("TWILIO_ACCOUNT_SID", "AC1")
    monkeypatch.setenv("TWILIO_NUMBER", "+15550001111")
    monkeypatch.setenv("CALLBACK_NUMBER", "+919999999999")
    placed = []

    async def fake_place(s):
        placed.append((s.callback_number, s.twilio_number))
        return "CAtest"

    monkeypatch.setattr(m, "place_callback", fake_place)
    monkeypatch.setattr(m, "_call_limiter", RateLimiter(max_calls=5, min_gap_s=60))

    assert client.post("/call-me").status_code == 403
    assert client.post("/call-me", headers={"X-Server-Secret": "wrong"}).status_code == 403
    # a body or query cannot change the destination
    r = client.post("/call-me?To=%2B1", json={"To": "+1"}, headers={"X-Server-Secret": "s3cret"})
    assert r.status_code == 200 and r.json() == {"call_sid": "CAtest"}
    assert placed == [("+919999999999", "+15550001111")]
    r2 = client.post("/call-me", headers={"X-Server-Secret": "s3cret"})
    assert r2.status_code == 429 and int(r2.headers["Retry-After"]) > 0
    assert len(placed) == 1


def test_rate_limiter_window():
    from dost.phone import RateLimiter

    rl = RateLimiter(max_calls=2, window_s=100, min_gap_s=10)
    assert rl.retry_after(0) == 0
    rl.record(0)
    assert rl.retry_after(5) == 5
    rl.record(20)
    assert rl.retry_after(30) == 70  # window full: wait until the first call ages out
    assert rl.retry_after(101) == 0


def test_voice_hashes_the_callee_on_outbound_calls(client):
    from dost.audio.twilio import caller_hash

    form = {"CallSid": "CA2", "From": "+15550001111", "To": "+919876543210", "Direction": "outbound-api"}
    sig = twilio_signature("https://dost.example/twilio/voice", form, "tok")
    r = client.post("/twilio/voice", data=form, headers={"X-Twilio-Signature": sig})
    assert caller_hash("+919876543210", "s3cret") in r.text
    assert caller_hash("+15550001111", "s3cret") not in r.text
