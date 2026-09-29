"""Durable, idempotent usage meter (SQLite).

Skill: ai-metering-billing — unique-key ingestion so producer retries never
double-count, period totals, and a Stripe-shaped `action="increment"` flush
plan (retry-safe by construction).
"""

from __future__ import annotations

import sqlite3
import threading
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    idempotency_key TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL,
    metric          TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    period_key      TEXT NOT NULL,
    ts              INTEGER NOT NULL
);
"""

_INSERT = """
INSERT INTO usage_events (idempotency_key, customer_id, metric, quantity, period_key, ts)
VALUES (?, ?, ?, ?, ?, ?)
"""

_TOTALS = """
SELECT customer_id, metric, SUM(quantity) AS total
FROM usage_events
WHERE period_key = ?
GROUP BY customer_id, metric
ORDER BY customer_id, metric
"""


class Meter:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def record(self, *, customer_id: str, metric: str, quantity: int,
               period_key: str, idempotency_key: str) -> bool:
        """Returns True when the event was new, False for a duplicate retry."""
        with self._lock:
            try:
                self._conn.execute(
                    _INSERT,
                    (idempotency_key, customer_id, metric, quantity,
                     period_key, int(time.time())),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                return False
        return True

    def totals(self, period_key: str) -> list[dict]:
        return [
            {"customer_id": c, "metric": m, "quantity": q}
            for c, m, q in self._conn.execute(_TOTALS, (period_key,))
        ]

    def flush_plan(self, period_key: str, action: str = "increment") -> list[dict]:
        """Stripe-shaped usage records; `increment` makes batch retries safe."""
        return [
            {"customer_id": c, "metric": m, "quantity": q,
             "action": action, "period": period_key}
            for c, m, q in self._conn.execute(_TOTALS, (period_key,))
        ]
