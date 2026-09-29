#!/usr/bin/env python
"""x402 paid-endpoint demo (FastAPI).

Protects GET /report behind an HTTP 402 payment challenge on Base Sepolia.

Usage:
    pip install "x402[fastapi,httpx,evm]" uvicorn python-dotenv
    set EVM_ADDRESS=0xYourTestnetAddress        (Base Sepolia receive address)
    python demo_x402_fastapi.py                  # serves on :8402

    python demo_x402_fastapi.py --smoke          # offline check: GET returns 402

The smoke check needs no network: the middleware issues the 402 challenge
before any facilitator call. Settlement only happens when a signed payment
is retried against the facilitator.
"""

from __future__ import annotations

import os
import sys

try:
    from fastapi import FastAPI
    from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
    from x402.http.middleware.fastapi import PaymentMiddlewareASGI
    from x402.http.types import RouteConfig
    from x402.mechanisms.evm.exact import ExactEvmServerScheme
    from x402.server import x402ResourceServer
except ImportError as exc:  # pragma: no cover
    sys.exit(
        f"missing dependency: {exc.name}\n"
        'install with: pip install "x402[fastapi,httpx,evm]" uvicorn'
    )

NETWORK = os.getenv("X402_NETWORK", "eip155:84532")  # Base Sepolia (testnet)
PAY_TO = os.getenv("EVM_ADDRESS", "0x000000000000000000000000000000000000dEaD")
PRICE = os.getenv("X402_PRICE", "$0.001")
FACILITATOR_URL = os.getenv("FACILITATOR_URL", "https://x402.org/facilitator")

app = FastAPI(title="x402 paid API demo")


def build_server() -> None:
    facilitator = HTTPFacilitatorClient(FacilitatorConfig(url=FACILITATOR_URL))
    server = x402ResourceServer(facilitator)
    server.register(NETWORK, ExactEvmServerScheme())

    routes = {
        "GET /report": RouteConfig(
            accepts=[
                PaymentOption(
                    scheme="exact",
                    pay_to=PAY_TO,
                    price=PRICE,
                    network=NETWORK,
                )
            ],
            mime_type="application/json",
            description="Paid weather report",
        )
    }
    app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)


build_server()


@app.get("/report")
def report() -> dict[str, str]:
    return {"report": "sunny", "paid": True, "network": NETWORK}


def smoke() -> int:
    """Offline assertion: an unpaid request must get HTTP 402."""
    from fastapi.testclient import TestClient

    response = TestClient(app).get("/report")
    assert response.status_code == 402, f"expected 402, got {response.status_code}"
    print(f"smoke OK: 402 Payment Required (price={PRICE}, network={NETWORK})")
    print(f"response headers/keys: {sorted(response.headers)} / {sorted(response.json())}")
    return 0


if __name__ == "__main__":
    if "--smoke" in sys.argv:
        raise SystemExit(smoke())
    import uvicorn

    print(f"GET http://127.0.0.1:8402/report  price={PRICE} network={NETWORK}")
    uvicorn.run(app, host="127.0.0.1", port=8402)
