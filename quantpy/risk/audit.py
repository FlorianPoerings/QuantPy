"""Tamper-evident audit trail.

Every decision (AI proposal, risk approval/rejection, order, kill switch,
login, legal acknowledgement) is appended as one JSON line.  Each line contains
the SHA-256 hash of the previous line, so later modification or deletion of
an entry is detectable with :meth:`AuditLog.verify`.

The log is an *evidence* tool (reconstruction of why an algorithm acted),
it is not a substitute for broker statements or tax records.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
from datetime import datetime, timezone
from typing import Any, Iterator

GENESIS = "0" * 64


class AuditLog:
    def __init__(self, path: str = "audit/audit_log.jsonl"):
        self.path = path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._last_hash = self._read_last_hash()

    def _read_last_hash(self) -> str:
        if not os.path.exists(self.path):
            return GENESIS
        last = GENESIS
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        last = json.loads(line)["hash"]
                    except (ValueError, KeyError):
                        pass
        return last

    @staticmethod
    def _digest(prev: str, ts: str, event: str, data: Any) -> str:
        payload = json.dumps([prev, ts, event, data], sort_keys=True,
                             separators=(",", ":"), default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def record(self, event: str, **data: Any) -> dict:
        with self._lock:
            ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
            data = json.loads(json.dumps(data, default=str))  # make JSON-safe
            h = self._digest(self._last_hash, ts, event, data)
            entry = {"ts": ts, "event": event, "data": data,
                     "prev": self._last_hash, "hash": h}
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._last_hash = h
            return entry

    def entries(self) -> Iterator[dict]:
        if not os.path.exists(self.path):
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)

    def tail(self, n: int = 50) -> list[dict]:
        rows = list(self.entries())
        return rows[-n:]

    def verify(self) -> tuple[bool, int, str]:
        """Return (ok, entries_checked, message)."""
        prev, n = GENESIS, 0
        try:
            for e in self.entries():
                n += 1
                if e["prev"] != prev:
                    return False, n, f"chain broken at entry {n}"
                if self._digest(e["prev"], e["ts"], e["event"], e["data"]) != e["hash"]:
                    return False, n, f"entry {n} was modified"
                prev = e["hash"]
        except (ValueError, KeyError) as exc:
            return False, n, f"unreadable entry after {n}: {exc}"
        return True, n, "ok"
