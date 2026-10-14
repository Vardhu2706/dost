"""SQLite memory. No audio, no phone numbers; transcripts expire."""

from __future__ import annotations

import sqlite3
import threading
import time

from dost.memory.models import UserRecord

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  user_hash TEXT PRIMARY KEY, created_at REAL NOT NULL, language_pref TEXT NOT NULL DEFAULT 'hi',
  summary TEXT NOT NULL DEFAULT '', open_loop TEXT, last_call_at REAL NOT NULL, call_count INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS calls(
  id TEXT PRIMARY KEY, user_hash TEXT NOT NULL, started_at REAL NOT NULL, ended_at REAL,
  final_phase TEXT, max_risk TEXT);
CREATE TABLE IF NOT EXISTS transcripts(
  call_id TEXT NOT NULL, turn_idx INTEGER NOT NULL, role TEXT NOT NULL, text TEXT NOT NULL,
  lang TEXT, expires_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS risk_events(call_id TEXT NOT NULL, ts REAL NOT NULL, level TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_calls_user ON calls(user_hash);
CREATE INDEX IF NOT EXISTS idx_tr_call ON transcripts(call_id);
"""


class Memory:
    def __init__(self, path: str, ttl_days: int = 7) -> None:
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self.ttl_days = ttl_days
        with self._lock:
            self._db.executescript(SCHEMA)
        self.purge_expired()

    # --- users ----------------------------------------------------------------
    def get_user(self, user_hash: str) -> UserRecord | None:
        with self._lock:
            row = self._db.execute(
                "SELECT user_hash, created_at, language_pref, summary, open_loop, last_call_at, call_count "
                "FROM users WHERE user_hash=?", (user_hash,)
            ).fetchone()
        return UserRecord(*row) if row else None

    def save_summary(
        self, user_hash: str, summary: str, open_loop: str | None, language_pref: str,
        now: float | None = None, count_call: bool = True,
    ) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._db.execute(
                "INSERT INTO users(user_hash, created_at, language_pref, summary, open_loop, last_call_at, call_count) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(user_hash) DO UPDATE SET language_pref=excluded.language_pref, "
                "summary=excluded.summary, open_loop=excluded.open_loop, last_call_at=excluded.last_call_at, "
                "call_count=call_count+?",
                (user_hash, now, language_pref, summary, open_loop, now, int(count_call), int(count_call)),
            )

    def forget(self, user_hash: str) -> bool:
        """Delete everything stored for this caller. Returns True if a user record existed."""
        with self._lock:
            ids = [r[0] for r in self._db.execute("SELECT id FROM calls WHERE user_hash=?", (user_hash,))]
            for cid in ids:
                self._db.execute("DELETE FROM transcripts WHERE call_id=?", (cid,))
                self._db.execute("DELETE FROM risk_events WHERE call_id=?", (cid,))
            self._db.execute("DELETE FROM calls WHERE user_hash=?", (user_hash,))
            cur = self._db.execute("DELETE FROM users WHERE user_hash=?", (user_hash,))
            return cur.rowcount > 0

    # --- calls ----------------------------------------------------------------
    def start_call(self, call_id: str, user_hash: str, started_at: float | None = None) -> None:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO calls(id, user_hash, started_at) VALUES(?,?,?)",
                (call_id, user_hash, time.time() if started_at is None else started_at),
            )

    def end_call(self, call_id: str, final_phase: str, max_risk: str, ended_at: float | None = None) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE calls SET ended_at=?, final_phase=?, max_risk=? WHERE id=?",
                (time.time() if ended_at is None else ended_at, final_phase, max_risk, call_id),
            )

    # --- transcripts (deleted once summarized; otherwise expire after TTL) ------
    def add_turn(self, call_id: str, idx: int, role: str, text: str, lang: str | None, now: float | None = None) -> None:
        now = time.time() if now is None else now
        with self._lock:
            self._db.execute(
                "INSERT INTO transcripts VALUES(?,?,?,?,?,?)",
                (call_id, idx, role, text, lang, now + self.ttl_days * 86400),
            )

    def transcript(self, call_id: str) -> list[tuple[str, str]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT role, text FROM transcripts WHERE call_id=? ORDER BY turn_idx", (call_id,)
            ).fetchall()
        return [(r[0], r[1]) for r in rows]

    def delete_transcript(self, call_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM transcripts WHERE call_id=?", (call_id,))

    def pending_calls(self, user_hash: str, exclude: str | None = None) -> list[str]:
        """Earlier calls of this caller whose transcripts were never summarized (oldest first)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT c.id FROM calls c WHERE c.user_hash=? AND c.id<>? AND EXISTS "
                "(SELECT 1 FROM transcripts t WHERE t.call_id=c.id) ORDER BY c.started_at",
                (user_hash, exclude or ""),
            ).fetchall()
        return [r[0] for r in rows]

    def purge_expired(self, now: float | None = None) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM transcripts WHERE expires_at < ?", (time.time() if now is None else now,)
            )

    # --- risk events: (call_id, ts, level), never content ---------------------
    def add_risk_event(self, call_id: str, level: str, ts: float | None = None) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO risk_events VALUES(?,?,?)", (call_id, time.time() if ts is None else ts, level)
            )

    def risk_events(self, call_id: str) -> list[tuple[float, str]]:
        with self._lock:
            return list(self._db.execute("SELECT ts, level FROM risk_events WHERE call_id=?", (call_id,)))

    def close(self) -> None:
        with self._lock:
            self._db.close()
