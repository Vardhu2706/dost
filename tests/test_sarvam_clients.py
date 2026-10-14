from urllib.parse import parse_qs, urlparse

import pytest

from dost.sarvam.stt import Final, Partial, SpeechStart, build_url, parse_event
from dost.sarvam.tts import config_message


def test_stt_url_has_required_params():
    q = parse_qs(urlparse(build_url(language_code="hi-IN", mode="codemix")).query)
    assert q["language_code"] == ["hi-IN"]
    assert q["model"] == ["saaras:v3-realtime"]
    assert q["mode"] == ["codemix"]
    assert q["encoding"] == ["linear16"]
    assert q["sample_rate"] == ["16000"]


def test_stt_parse_events():
    assert parse_event({"event": "vad.speech_start"}) == SpeechStart()
    assert parse_event({"event": "transcript.partial", "text": "हेलो", "language": "en-IN"}) == Partial(
        "हेलो", "en-IN"
    )
    assert parse_event(
        {"event": "transcript.final", "text": "हेलो", "language": "hi-IN", "language_confidence": 0.97}
    ) == Final("हेलो", "hi-IN", 0.97)
    assert parse_event({"event": "pong"}) is None
    assert parse_event({"event": "error", "is_fatal": False, "code": "x"}) is None


def test_stt_fatal_error_raises():
    with pytest.raises(RuntimeError):
        parse_event({"event": "error", "is_fatal": True, "code": "bad", "message": "m"})


def test_tts_config_is_raw_pcm():
    data = config_message("amit_hi_conversational", "hi-IN", 24000)["data"]
    assert data["output_audio_codec"] == "linear16"
    assert data["speech_sample_rate"] == 24000
    assert data["speaker"] == "amit_hi_conversational"


def test_normalize_for_tts_plain_punctuation():
    from dost.sarvam.tts import normalize_for_tts

    assert normalize_for_tts("अरे यार... फिर से?") == "अरे यार, फिर से?"
    assert normalize_for_tts("हम्म…") == "हम्म।"
    assert normalize_for_tts("I get it —  tell me more...") == "I get it, tell me more."
    assert normalize_for_tts("ठीक है। बताओ।") == "ठीक है। बताओ।"
    assert normalize_for_tts("wait.... what?") == "wait, what?"
    assert normalize_for_tts("...") == "."


def test_config_message_carries_pitch_and_loudness():
    data = config_message("v", "hi-IN", 24000, pace=1.1, pitch=0.1, loudness=1.2)["data"]
    assert (data["pace"], data["pitch"], data["loudness"]) == (1.1, 0.1, 1.2)
