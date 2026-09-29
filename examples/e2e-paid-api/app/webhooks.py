"""Stripe webhook receiver: raw-body signature verification + idempotent dispatch.

Skill: ai-metering-billing — webhooks are the source of truth; Stripe
retries until it gets a 2xx and delivers at-least-once, so every event is
idempotency-keyed by its `event.id`.

    POST /webhooks/stripe        # raw body verified against STRIPE_WEBHOOK_SECRET
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sqlite3
import threading
from typing import Callable

from fastapi import FastAPI, HTTPException, Request
from stripe import SignatureVerificationError, WebhookSignature

EventHandler = Callable[[dict], None]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS stripe_events (
    event_id TEXT PRIMARY KEY,   -- evt_... from Stripe: replay idempotency key
    type     TEXT NOT NULL,
    ts       INTEGER NOT NULL
);
"""


class EventStore:
    """Idempotent event journal: a replayed webhook must not re-run handlers."""

    def __init__(self, path: str = ":memory:") -> None:
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._lock = threading.Lock()

    def first_time(self, event_id: str, event_type: str, ts: int) -> bool:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO stripe_events VALUES (?, ?, ?)",
                    (event_id, event_type, ts),
                )
                self._conn.commit()
            except sqlite3.IntegrityError:
                return False
        return True


def verify_signature(payload: bytes, sig_header: str, secret: str,
                     tolerance: int = 300) -> None:
    """Raise SignatureVerificationError unless HMAC over `t.payload` matches."""
    WebhookSignature.verify_header(payload, sig_header, secret, tolerance)


def register_stripe_webhook(
    app: FastAPI,
    handlers: dict[str, EventHandler] | None = None,
    store: EventStore | None = None,
) -> None:
    """Attach POST /webhooks/stripe. Handlers: event_type -> callable(obj)."""
    handlers = handlers or {}
    store = store or EventStore()

    @app.post("/webhooks/stripe")
    async def stripe_webhook(request: Request) -> dict:
        secret = os.environ.get("STRIPE_WEBHOOK_SECRET")
        if not secret:
            raise HTTPException(503, "STRIPE_WEBHOOK_SECRET not configured")

        payload = await request.body()          # RAW body: signature covers bytes
        sig_header = request.headers.get("stripe-signature", "")
        try:
            verify_signature(payload, sig_header, secret)
        except SignatureVerificationError as exc:
            raise HTTPException(400, f"bad signature: {exc}")

        event = json.loads(payload)
        event_id, event_type = event["id"], event["type"]

        if not store.first_time(event_id, event_type, int(event.get("created", 0))):
            return {"received": True, "duplicate": True}   # 200: stop retries

        handler = handlers.get(event_type)
        if handler:
            handler(event["data"]["object"])    # handler failure -> 500 -> Stripe retries
        return {"received": True, "handled": bool(handler)}


def default_handlers(invoice_state: dict[str, str]) -> dict[str, EventHandler]:
    """Subscription lifecycle: paid / past_due state keyed by invoice id."""
    def on_paid(obj: dict) -> None:
        invoice_state[obj["id"]] = "paid"

    def on_payment_failed(obj: dict) -> None:
        invoice_state[obj["id"]] = "past_due"

    def on_subscription_updated(obj: dict) -> None:
        invoice_state.setdefault(obj.get("latest_invoice", obj["id"]), "updated")

    return {
        "invoice.paid": on_paid,
        "invoice.payment_failed": on_payment_failed,
        "customer.subscription.updated": on_subscription_updated,
    }


def sign(payload: bytes, secret: str, timestamp: int | None = None) -> str:
    """Test helper: build a Stripe-Signature header the verifier accepts."""
    import time

    timestamp = timestamp or int(time.time())
    mac = hmac.new(secret.encode(), f"{timestamp}.".encode() + payload,
                   hashlib.sha256).hexdigest()
    return f"t={timestamp},v1={mac}"
