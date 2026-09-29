"""Append-only double-entry ledger (SQLite).

Skill: payments-ledger-reconciliation — every money movement is a balanced
multi-leg entry keyed by a stable id, so webhook/settlement replays post once
and the trial balance always sums to zero. Corrections are new entries, never
updates.
"""

from __future__ import annotations

import sqlite3
import threading
import time

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entries (
    entry_id    TEXT PRIMARY KEY,   -- idempotency key (settlement/payment id)
    source      TEXT NOT NULL,
    description TEXT NOT NULL,
    ts          INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS postings (
    entry_id TEXT NOT NULL REFERENCES entries(entry_id),
    account  TEXT NOT NULL,         -- 1000 cash, 4000 revenue, 5000 fees, ...
    amount   INTEGER NOT NULL       -- signed minor units: +debit, -credit
);
"""


class Ledger:
    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def post(self, entry_id: str, postings: list[tuple[str, int]],
             *, source: str = "manual", description: str = "") -> bool:
        """Post one balanced entry; False when entry_id already exists."""
        if not postings:
            raise ValueError(f"{entry_id}: entry needs at least one posting")
        if sum(amount for _, amount in postings) != 0:
            raise ValueError(f"{entry_id}: postings do not balance")
        with self._lock:
            try:
                self._conn.execute("BEGIN")
                self._conn.execute(
                    "INSERT INTO entries VALUES (?, ?, ?, ?)",
                    (entry_id, source, description, int(time.time())),
                )
                self._conn.executemany(
                    "INSERT INTO postings VALUES (?, ?, ?)",
                    [(entry_id, account, amount) for account, amount in postings],
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                self._conn.rollback()
                return False
            except Exception:
                self._conn.rollback()
                raise
        return True

    def balances(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT account, SUM(amount) FROM postings"
            " GROUP BY account ORDER BY account"
        )
        return {account: total for account, total in rows}

    @property
    def trial_balance(self) -> int:
        (total,) = self._conn.execute("SELECT COALESCE(SUM(amount), 0)"
                                      " FROM postings").fetchone()
        return total
