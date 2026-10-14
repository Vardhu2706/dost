"""Callback mode: Twilio rings the verified CALLBACK_NUMBER and runs the normal voice flow."""

from __future__ import annotations

import hmac
import time
from collections import deque

import httpx

from dost.config import Settings

CALLS_URL = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Calls.json"


class RateLimiter:
    """At most `max_calls` per `window_s`, and at least `min_gap_s` between calls (in-memory)."""

    def __init__(self, max_calls: int = 5, window_s: float = 3600.0, min_gap_s: float = 60.0) -> None:
        self.max_calls, self.window_s, self.min_gap_s = max_calls, window_s, min_gap_s
        self._times: deque[float] = deque()

    def retry_after(self, now: float | None = None) -> float:
        """Seconds to wait before a call is allowed (0 if allowed now)."""
        now = time.monotonic() if now is None else now
        while self._times and now - self._times[0] > self.window_s:
            self._times.popleft()
        waits = [0.0]
        if self._times:
            waits.append(self.min_gap_s - (now - self._times[-1]))
        if len(self._times) >= self.max_calls:
            waits.append(self.window_s - (now - self._times[0]))
        return max(waits)

    def record(self, now: float | None = None) -> None:
        self._times.append(time.monotonic() if now is None else now)


def secret_ok(provided: str | None, secret: str) -> bool:
    return bool(secret) and bool(provided) and hmac.compare_digest(provided.encode(), secret.encode())


def callback_configured(s: Settings) -> bool:
    return all(
        (s.twilio_account_sid, s.twilio_auth_token, s.twilio_number, s.callback_number,
         s.public_base_url, s.server_secret)
    )


async def place_callback(s: Settings, client: httpx.AsyncClient | None = None) -> str:
    """Create the outbound call. The destination is always the CALLBACK_NUMBER from the env."""
    owns = client is None
    client = client or httpx.AsyncClient(timeout=15.0)
    try:
        resp = await client.post(
            CALLS_URL.format(sid=s.twilio_account_sid),
            auth=(s.twilio_account_sid, s.twilio_auth_token),
            data={
                "To": s.callback_number,
                "From": s.twilio_number,
                "Url": f"{s.public_base_url}/twilio/voice",
                "Method": "POST",
            },
        )
        if resp.status_code >= 300:
            raise RuntimeError(f"Twilio {resp.status_code}: {resp.text[:300]}")
        return resp.json().get("sid", "")
    finally:
        if owns:
            await client.aclose()
