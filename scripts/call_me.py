"""Ask the running Dost server to ring CALLBACK_NUMBER (server-side rate limit applies).

Usage: uv run python scripts/call_me.py [--url http://127.0.0.1:8000]
Reads SERVER_SECRET from .env / .env.local. Pick up the phone; Dost speaks first.
"""

from __future__ import annotations

import argparse
import sys

import httpx

from dost.config import load_settings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    args = ap.parse_args()
    secret = load_settings().server_secret
    if not secret:
        print("SERVER_SECRET is not set", file=sys.stderr)
        return 2
    r = httpx.post(f"{args.url}/call-me", headers={"X-Server-Secret": secret}, timeout=20)
    print(r.status_code, r.text, r.headers.get("Retry-After", ""))
    return 0 if r.status_code == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
