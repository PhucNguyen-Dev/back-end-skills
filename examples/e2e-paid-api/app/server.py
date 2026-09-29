"""x402-paid API with usage metering on the paid path.

Skills: agentic-payments-protocols (402 middleware), ai-metering-billing
(durable idempotent meter keyed to the payment's EIP-3009 nonce),
payments-ledger-reconciliation (balanced post per settlement).

    python -m app.server                  # serves on :8402
    GET  /paid/report                     # 402 without payment, 200 with
    GET  /usage?period=2026-09            # metered totals
    GET  /flush?period=2026-09            # Stripe-shaped increment plan
    GET  /balance                         # ledger accounts + trial balance
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from fastapi import FastAPI, Query, Request
from x402.http import (
    FacilitatorConfig,
    HTTPFacilitatorClient,
    PaymentOption,
    decode_payment_signature_header,
)
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

from app.ledger import Ledger
from app.meter import Meter
from app.webhooks import default_handlers, register_stripe_webhook

NETWORK = os.getenv("X402_NETWORK", "eip155:84532")  # Base Sepolia (testnet)
PAY_TO = os.getenv("EVM_ADDRESS", "0x000000000000000000000000000000000000dEaD")
PRICE = os.getenv("X402_PRICE", "$0.001")
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://x402.org/facilitator")

PRICE_ATOMIC = int(round(float(PRICE.lstrip("$")) * 1_000_000))  # USDC, 6 dp


def _dig(obj: object, *names: str) -> object | None:
    for name in names:
        if isinstance(obj, dict):
            if name in obj:
                return obj[name]
        else:
            value = getattr(obj, name, None)
            if value is not None:
                return value
    return None


def _payment_signature(request: Request) -> dict | object | None:
    header = request.headers.get("payment-signature")
    if not header:
        return None
    try:
        return decode_payment_signature_header(header)
    except Exception:
        return None


def payer_and_nonce(request: Request) -> tuple[str, str | None]:
    """Identity for metering: payer address + EIP-3009 nonce (idempotency key).

    The middleware already verified this signature before the handler ran.
    """
    signature = _payment_signature(request)
    if signature is None:
        return "anonymous", None
    authorization = _dig(_dig(signature, "payload"), "authorization")
    payer = _dig(authorization, "from", "sender", "owner")
    nonce = _dig(authorization, "nonce")
    return (str(payer) if payer else "anonymous", str(nonce) if nonce else None)


def period_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def create_app(meter: Meter | None = None, ledger: Ledger | None = None) -> FastAPI:
    meter = meter or Meter()
    ledger = ledger or Ledger()
    app = FastAPI(title="e2e paid API")

    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
    server = x402ResourceServer(facilitator)
    server.register(NETWORK, ExactEvmServerScheme())
    routes = {
        "GET /paid/report": RouteConfig(
            accepts=[PaymentOption(scheme="exact", pay_to=PAY_TO,
                                   price=PRICE, network=NETWORK)],
            mime_type="application/json",
            description="Paid weather report",
        )
    }
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)
    register_stripe_webhook(app, default_handlers({}))

    @app.get("/paid/report")
    def paid_report(request: Request) -> dict:
        payer, nonce = payer_and_nonce(request)
        # Payment nonce is unique per authorization -> retries never double-meter.
        key = f"report:{nonce}" if nonce else f"report:{uuid.uuid4().hex}"
        recorded = meter.record(
            customer_id=payer,
            metric="report_call",
            quantity=1,
            period_key=period_now(),
            idempotency_key=key,
        )
        # Middleware settles the payment before this handler runs in
        # production; post cash + revenue keyed by the payment nonce so
        # replays are idempotent here too. Amounts are USDC atomic units.
        ledger.post(
            f"settle:{key}",
            [("1000", PRICE_ATOMIC), ("4000", -PRICE_ATOMIC)],
            source="x402",
            description="x402 payment settled",
        )
        return {
            "report": "sunny",
            "network": NETWORK,
            "payer": payer,
            "charged_atomic": str(PRICE_ATOMIC),
            "metered": recorded,
        }

    @app.get("/usage")
    def usage(period: str = Query(default_factory=period_now)) -> dict:
        return {"period": period, "totals": meter.totals(period)}

    @app.get("/balance")
    def balance() -> dict:
        return {"balances": ledger.balances(),
                "trial_balance": ledger.trial_balance}

    @app.get("/flush")
    def flush(period: str = Query(default_factory=period_now)) -> dict:
        plan = meter.flush_plan(period)
        if not plan:
            return {"period": period, "records": [], "sent_to_stripe": False}
        stripe_key = os.getenv("STRIPE_API_KEY")
        sub_item = os.getenv("STRIPE_SUBSCRIPTION_ITEM_ID")
        if stripe_key and sub_item:
            import time
            import stripe

            stripe.api_key = stripe_key
            for record in plan:
                stripe.SubscriptionItem.create_usage_record(
                    sub_item,
                    quantity=record["quantity"],
                    timestamp=int(time.time()),
                    action="increment",
                    idempotency_key=f"{sub_item}:{record['period']}"
                                    f":{record['metric']}"
                                    f":{record['customer_id']}"[:255],
                )
            return {"period": period, "records": plan, "sent_to_stripe": True}
        return {"period": period, "records": plan, "sent_to_stripe": False}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8402"))
    print(f"GET http://127.0.0.1:{port}/paid/report  price={PRICE} network={NETWORK}")
    uvicorn.run(app, host="127.0.0.1", port=port)
