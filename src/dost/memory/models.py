"""Memory records and identity hashing (pseudonymized, not anonymous)."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass


def normalize_number(number: str) -> str:
    """Keep digits and a leading '+', so '+91 98765-43210' and '+919876543210' hash the same."""
    s = number.strip()
    return ("+" if s.startswith("+") else "") + re.sub(r"\D", "", s)


def hash_number(number: str, secret: str) -> str:
    """HMAC-SHA256(phone_number, SERVER_SECRET), hex. The only form of a number we keep."""
    return hmac.new(secret.encode(), normalize_number(number).encode(), hashlib.sha256).hexdigest()


@dataclass(frozen=True)
class UserRecord:
    user_hash: str
    created_at: float
    language_pref: str
    summary: str
    open_loop: str | None
    last_call_at: float
    call_count: int
