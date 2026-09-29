"""Webhook tests: signature verification, replay idempotency, dispatch.

    pytest tests/test_webhooks.py -q
"""

from __future__ import annotations

import json
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.webhooks import default_handlers, register_stripe_webhook, sign

SECRET = "whsec_test_secret"
EVENT = {
    "id": "evt_test_001",
    "type": "invoice.paid",
    "created": 1_700_000_000,
    "data": {"object": {"id": "in_123", "amount_due": 2500}},
}


def webhook_client(handlers=None):
    app = FastAPI()
    register_stripe_webhook(app, handlers=handlers)
    return TestClient(app)


def post_event(client: TestClient, payload: dict, secret: str = SECRET,
               timestamp: int | None = None) -> object:
    body = json.dumps(payload).encode()
    return client.post(
        "/webhooks/stripe",
        content=body,
        headers={"stripe-signature": sign(body, secret, timestamp)},
    )


def test_valid_signature_dispatches_once(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    calls: list[str] = []
    client = webhook_client({"invoice.paid": lambda obj: calls.append(obj["id"])})

    first = post_event(client, EVENT)
    replay = post_event(client, EVENT)          # Stripe retries until 2xx

    assert first.status_code == 200
    assert first.json() == {"received": True, "handled": True}
    assert replay.status_code == 200
    assert replay.json() == {"received": True, "duplicate": True}
    assert calls == ["in_123"]                  # handler ran exactly once


def test_bad_signature_rejected(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    client = webhook_client({})
    body = json.dumps(EVENT).encode()
    response = client.post(
        "/webhooks/stripe", content=body,
        headers={"stripe-signature": "t=1,v1=" + "0" * 64},
    )
    assert response.status_code == 400


def test_expired_timestamp_rejected(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    client = webhook_client({})
    stale = int(time.time()) - 3600             # outside 300s tolerance
    response = post_event(client, EVENT, timestamp=stale)
    assert response.status_code == 400


def test_unconfigured_secret_fails_closed(monkeypatch):
    monkeypatch.delenv("STRIPE_WEBHOOK_SECRET", raising=False)
    client = webhook_client({})
    response = post_event(client, EVENT, secret="whatever")
    assert response.status_code == 503          # no secret -> verify nothing


def test_default_handlers_track_invoice_state(monkeypatch):
    monkeypatch.setenv("STRIPE_WEBHOOK_SECRET", SECRET)
    state: dict[str, str] = {}
    app = FastAPI()
    register_stripe_webhook(app, default_handlers(state))
    client = TestClient(app)

    assert post_event(client, EVENT).json()["handled"] is True
    assert state == {"in_123": "paid"}

    failed = {**EVENT, "id": "evt_test_002", "type": "invoice.payment_failed"}
    post_event(client, failed)
    assert state["in_123"] == "past_due"

    unhandled = {**EVENT, "id": "evt_test_003", "type": "charge.refunded"}
    response = post_event(client, unhandled)
    assert response.json() == {"received": True, "handled": False}
