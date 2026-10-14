"""Runtime configuration, read from the environment (.env, then .env.local)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    sarvam_api_key: str
    server_secret: str
    db_path: str
    default_lang: str
    voice_hi: str
    voice_te: str
    llm_model: str
    transcript_ttl_days: int
    soft_wind_down_min: int
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_number: str = ""
    callback_number: str = ""  # verified mobile that /call-me rings
    voice_en: str = "sunny_en_social"
    public_base_url: str = ""  # tunnel URL, no trailing slash


def load_settings() -> Settings:
    load_dotenv(ROOT / ".env")
    load_dotenv(ROOT / ".env.local")
    key = os.environ.get("SARVAM_API_KEY", "")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set (put it in .env or .env.local)")
    return Settings(
        sarvam_api_key=key,
        server_secret=os.environ.get("SERVER_SECRET", ""),
        db_path=os.environ.get("DB_PATH", "dost.db"),
        default_lang=os.environ.get("DEFAULT_LANG", "hi-IN"),
        voice_hi=os.environ.get("VOICE_HI", "amit_hi_conversational"),
        voice_te=os.environ.get("VOICE_TE", "tarun_te_narration"),
        llm_model=os.environ.get("LLM_MODEL", "sarvam-105b"),
        transcript_ttl_days=int(os.environ.get("TRANSCRIPT_TTL_DAYS", "7")),
        soft_wind_down_min=int(os.environ.get("SOFT_WIND_DOWN_MIN", "15")),
        twilio_account_sid=os.environ.get("TWILIO_ACCOUNT_SID", ""),
        twilio_auth_token=os.environ.get("TWILIO_AUTH_TOKEN", ""),
        twilio_number=os.environ.get("TWILIO_NUMBER", ""),
        callback_number=os.environ.get("CALLBACK_NUMBER", ""),
        voice_en=os.environ.get("VOICE_EN", "sunny_en_social"),
        public_base_url=os.environ.get("PUBLIC_BASE_URL", "").rstrip("/"),
    )
