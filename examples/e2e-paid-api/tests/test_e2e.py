"""Offline end-to-end tests: 402 challenge, metering idempotency, policy gates.

    uv run --with pytest --with fastapi --with httpx \
        --with "x402[fastapi,httpx,evm]" pytest tests -q
"""

from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient
from starlette.requests import Request
from x402 import PaymentPayload, PaymentRequirements
from x402.http import encode_payment_signature_header

from app.buyer import intent_from_requirements
from app.ledger import Ledger
from app.meter import Meter
from app.policy import PaymentIntent, SessionBudget, SpendPolicy, authorize
from app.server import PRICE_ATOMIC, create_app, period_now

PAY_TO = "0x000000000000000000000000000000000000dEaD"
USDC = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"


def signature_header(payer: str, nonce: str) -> str:
    """Fabricate a PaymentPayload header (structurally valid, unsigned)."""
    requirement = PaymentRequirements(
        scheme="exact", network="eip155:84532", asset=USDC, amount="1000",
        pay_to=PAY_TO, max_timeout_seconds=60,
        extra={"name": "USDC", "version": "2"},
    )
    payload = PaymentPayload.model_validate({
        "x402_version": 2,
        "payload": {
            "signature": "0x" + "00" * 65,
            "authorization": {
                "from": payer, "to": PAY_TO, "value": "1000",
                "validAfter": "0", "validBefore": "9999999999",
                "nonce": nonce,
            },
        },
        "accepted": requirement.model_dump(),
        "resource": {"url": "http://test/paid/report"},
    })
    return encode_payment_signature_header(payload)


def fake_request(signature: str | None = None) -> Request:
    headers = [] if signature is None else [
        (b"payment-signature", signature.encode("ascii"))
    ]
    return Request({"type": "http", "method": "GET",
                    "path": "/paid/report", "headers": headers})


def report_endpoint(meter: Meter, ledger: Ledger | None = None):
    app = create_app(meter, ledger)
    return next(route.endpoint for route in app.routes
                if getattr(route, "path", "") == "/paid/report")


def test_unpaid_request_gets_402():
    client = TestClient(create_app())
    response = client.get("/paid/report")
    assert response.status_code == 402
    assert "PAYMENT-REQUIRED" in {k.upper() for k in response.headers}


def test_handler_meters_once_per_payment_nonce():
    meter = Meter()
    handler = report_endpoint(meter)

    first = handler(fake_request(signature_header("0xPAYER", "0x" + "11" * 32)))
    retry = handler(fake_request(signature_header("0xPAYER", "0x" + "11" * 32)))

    assert first["payer"] == "0xPAYER"
    assert first["metered"] is True
    assert retry["metered"] is False  # same EIP-3009 nonce -> duplicate rejected
    assert meter.totals(period_now()) == [
        {"customer_id": "0xPAYER", "metric": "report_call", "quantity": 1}
    ]


def test_handler_without_signature_meters_anonymously():
    meter = Meter()
    handler = report_endpoint(meter)
    out = handler(fake_request())
    assert out["payer"] == "anonymous"
    assert out["metered"] is True


def test_usage_and_flush_endpoints():
    meter = Meter()
    handler = report_endpoint(meter)
    handler(fake_request(signature_header("0xPAYER", "0x" + "22" * 32)))
    client = TestClient(create_app(meter))

    usage = client.get("/usage", params={"period": period_now()}).json()
    assert usage["totals"][0]["quantity"] == 1

    flush = client.get("/flush", params={"period": period_now()}).json()
    assert flush["sent_to_stripe"] is False
    assert flush["records"][0]["action"] == "increment"


def test_meter_concurrent_retries_record_once():
    """N threads replaying one idempotency key -> exactly one usage row."""
    from concurrent.futures import ThreadPoolExecutor

    meter = Meter()
    kwargs = dict(customer_id="0xPAYER", metric="report_call", quantity=1,
                  period_key=period_now(),
                  idempotency_key="report:0x" + "77" * 32)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: meter.record(**kwargs), range(16)))

    assert sum(results) == 1
    assert meter.totals(period_now())[0]["quantity"] == 1


def test_ledger_posts_once_per_payment():
    meter, ledger = Meter(), Ledger()
    handler = report_endpoint(meter, ledger)

    handler(fake_request(signature_header("0xPAYER", "0x" + "33" * 32)))
    handler(fake_request(signature_header("0xPAYER", "0x" + "33" * 32)))  # replay
    handler(fake_request(signature_header("0xPAYER", "0x" + "44" * 32)))  # new nonce

    assert ledger.balances() == {
        "1000": 2 * PRICE_ATOMIC,   # cash up twice (two distinct payments)
        "4000": -2 * PRICE_ATOMIC,  # revenue
    }
    assert ledger.trial_balance == 0


def test_balance_endpoint_reflects_ledger():
    meter, ledger = Meter(), Ledger()
    handler = report_endpoint(meter, ledger)
    handler(fake_request(signature_header("0xPAYER", "0x" + "55" * 32)))

    client = TestClient(create_app(meter, ledger))
    out = client.get("/balance").json()
    assert out["balances"]["1000"] == PRICE_ATOMIC
    assert out["balances"]["4000"] == -PRICE_ATOMIC
    assert out["trial_balance"] == 0


def test_ledger_rejects_unbalanced_and_duplicates():
    ledger = Ledger()
    assert ledger.post("e1", [("1000", 100), ("4000", -100)])
    assert not ledger.post("e1", [("1000", 100), ("4000", -100)])  # idempotent
    try:
        ledger.post("e2", [("1000", 100)])
        raise AssertionError("unbalanced entry accepted")
    except ValueError:
        pass
    assert ledger.trial_balance == 0


def test_policy_matrix():
    policy = SpendPolicy(
        per_tx_limit_atomic=1_000_000,
        session_limit_atomic=2_000_000,
        human_approval_threshold_atomic=500_000,
        allowlisted_payees=frozenset({"0xGOOD"}),
    )
    budget = SessionBudget(policy.session_limit_atomic)

    good = PaymentIntent("0xGOOD", 100_000, "eip155:84532")
    assert authorize(good, policy, budget).approved

    unknown = PaymentIntent("0xEVIL", 100_000, "eip155:84532")
    assert authorize(unknown, policy, budget).outcome == "denied"

    over_cap = PaymentIntent("0xGOOD", 1_000_001, "eip155:84532")
    assert authorize(over_cap, policy, budget).reasons == ("per_tx_limit",)

    big = PaymentIntent("0xGOOD", 600_000, "eip155:84532")
    assert authorize(big, policy, budget).outcome == "pending_human"
    assert authorize(big, policy, budget, human_confirmed=True).approved

    # Session budget is committed by the caller after an approved payment.
    small = PaymentIntent("0xGOOD", 400_000, "eip155:84532")
    for _ in range(3):
        assert authorize(small, policy, budget).approved
        budget.commit(400_000)
    assert budget.spent == 1_200_000

    # 1.2M spent + 900k > 2M session limit -> denied before any signing.
    near_limit = PaymentIntent("0xGOOD", 900_000, "eip155:84532")
    assert authorize(near_limit, policy, budget).reasons == ("session_limit",)

    wrong_chain = PaymentIntent("0xGOOD", 1_000, "eip155:1")
    assert authorize(wrong_chain, policy, budget).reasons == ("network_not_allowed",)


def test_buyer_intent_mapping():
    requirements = SimpleNamespace(
        pay_to=PAY_TO, amount="1000", network="eip155:84532",
        asset=USDC, extra={"name": "USDC"},
    )
    intent = intent_from_requirements(requirements)
    assert intent.payee == PAY_TO
    assert intent.amount_atomic == 1000
    assert intent.asset == "USDC"  # recognized USDC contract mapped to symbol
