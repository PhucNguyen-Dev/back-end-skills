#!/usr/bin/env python
"""Durable metering demo (stdlib only; Stripe optional).

Pipeline: events -> SQLite table with unique idempotency key -> period totals
-> retry-safe usage flush preview (action="increment").

    python demo_metering.py            # offline self-test, prints the flush plan
    python demo_metering.py --live     # also POSTs usage records to Stripe
                                        # (needs STRIPE_API_KEY + usage target)
"""

from __future__ import annotations

import os
import sqlite3
import sys
import time
import uuid
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_events (
    idempotency_key TEXT PRIMARY KEY,
    customer_id     TEXT NOT NULL,
    metric          TEXT NOT NULL,
    quantity        INTEGER NOT NULL,
    period_key      TEXT NOT NULL,
    ts              INTEGER NOT NULL
);
"""

INSERT = """
INSERT INTO usage_events (idempotency_key, customer_id, metric, quantity, period_key, ts)
VALUES (?, ?, ?, ?, ?, ?)
"""

TOTALS = """
SELECT customer_id, metric, SUM(quantity) AS total
FROM usage_events
WHERE period_key = ?
GROUP BY customer_id, metric
ORDER BY customer_id, metric
"""


def open_db(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn


def ingest(conn: sqlite3.Connection, event: dict) -> bool:
    """Returns True if the event was new, False if it was a duplicate."""
    try:
        conn.execute(
            INSERT,
            (
                event["idempotency_key"],
                event["customer_id"],
                event["metric"],
                event["quantity"],
                event["period_key"],
                int(time.time()),
            ),
        )
    except sqlite3.IntegrityError:
        return False
    return True


def flush_plan(conn: sqlite3.Connection, period_key: str) -> list[dict]:
    """Stripe-shaped usage records. Increment makes batch retries safe."""
    return [
        {"customer_id": c, "metric": m, "quantity": q,
         "action": "increment", "period": period_key}
        for c, m, q in conn.execute(TOTALS, (period_key,))
    ]


def send_to_stripe(records: list[dict]) -> None:
    """Live flush. Requires stripe installed + STRIPE_API_KEY + target item ids."""
    import stripe

    stripe.api_key = os.environ["STRIPE_API_KEY"]
    sub_item_id = os.environ["STRIPE_SUBSCRIPTION_ITEM_ID"]
    for rec in records:
        stripe.SubscriptionItem.create_usage_record(
            sub_item_id,
            quantity=rec["quantity"],
            timestamp=int(time.time()),
            action="increment",
            idempotency_key=f"{sub_item_id}:{rec['period']}:{rec['metric']}"
                            f":{rec['customer_id']}"[:255],
        )
        print(f"stripe usage recorded: {rec}")


def self_test() -> int:
    conn = open_db()
    period = "2026-09"
    base = {"customer_id": "org_42", "metric": "llm_tokens_out",
            "period_key": period}

    # Three real events + two retries (same idempotency keys).
    events = [
        {**base, "idempotency_key": "evt-1", "quantity": 1280},
        {**base, "idempotency_key": "evt-2", "quantity": 640},
        {**base, "idempotency_key": "evt-3", "quantity": 320},
        {**base, "idempotency_key": "evt-1", "quantity": 1280},  # retry
        {**base, "idempotency_key": "evt-2", "quantity": 640},   # retry
    ]
    accepted = [ingest(conn, e) for e in events]
    assert accepted == [True, True, True, False, False], accepted

    plan = flush_plan(conn, period)
    assert plan == [{"customer_id": "org_42", "metric": "llm_tokens_out",
                     "quantity": 2240, "action": "increment",
                     "period": period}], plan

    # Re-running the flush plan is idempotent (same totals, increment semantics).
    assert flush_plan(conn, period) == plan

    print("self-test OK")
    print(f"ingested {sum(accepted)}/{len(events)} events "
          f"({len(events) - sum(accepted)} duplicate retries rejected)")
    for rec in plan:
        print(f"flush -> {rec}")
    return 0


if __name__ == "__main__":
    if "--live" in sys.argv:
        db = Path("metering.sqlite")
        if not db.exists():
            sys.exit("metering.sqlite not found - populate it via ingest() first")
        conn = open_db(str(db))
        period = sys.argv[sys.argv.index("--live") + 1] if len(sys.argv) > 2 else time.strftime("%Y-%m")
        plan = flush_plan(conn, period)
        if not plan:
            sys.exit(f"no usage events for period {period}")
        send_to_stripe(plan)
        raise SystemExit(0)
    raise SystemExit(self_test())
