---
name: agentic-payments-protocols
description: Build HTTP and agent payment flows with x402 (HTTP 402 pay-per-request), AP2 mandates (proof an agent is allowed to spend), MPP sessions, and ACP checkout. Use when adding paid endpoints, letting an agent buy services, choosing between payment protocols, or verifying agent payment authority.
license: MIT
compatibility: Python examples use the x402 SDK (pip install "x402[fastapi,httpx,evm]") and optional ap2 SDK; network access needed only for live settlement.
metadata:
  version: "1.0.0"
  domain: ai-payment-infra
---

# Agentic Payment Protocols

Four open protocols define how AI agents pay. They are complementary layers,
not competitors. Pick by the question you need to answer:

| Protocol | Layer | Question it answers | Steward |
| --- | --- | --- | --- |
| **AP2** | Authorization | "Is this agent allowed to spend?" | Google, FIDO Alliance |
| **ACP** | Checkout | "How does the agent buy from a merchant?" | OpenAI, Stripe |
| **x402** | Settlement | "How does money move per HTTP request?" | x402 Foundation (Linux Foundation) |
| **MPP** | Sessions | "How does an agent stream spend under a limit?" | Tempo, Stripe |

## Choose a route

| Your task | Route | Read |
| --- | --- | --- |
| Charge for an API endpoint per call (sub-dollar, machine-to-machine) | x402 | [references/x402.md](references/x402.md) |
| Charge for AI work where cost varies per request (tokens) | x402 `upto` scheme | [references/x402.md](references/x402.md#variable-pricing-upto) |
| Prove a human authorized an agent's purchase (enterprise audit) | AP2 mandates | [references/ap2.md](references/ap2.md) |
| Agent buys goods/services from a merchant storefront | ACP (+ AP2 on top) | [references/mpp-acp.md](references/mpp-acp.md) |
| Agent pre-authorizes a spend cap, then consumes continuously | MPP sessions | [references/mpp-acp.md](references/mpp-acp.md) |
| Unsure | Decision matrix | [references/protocol-selection.md](references/protocol-selection.md) |

## The x402 flow (the default for paid APIs)

No account, no API key — payment is part of HTTP:

1. Agent sends a normal request to a paid endpoint.
2. Server replies `402 Payment Required` with machine-readable requirements
   (`amount`, `asset`, `network`, `payTo`, `scheme`) in the
   `PAYMENT-REQUIRED` header.
3. Agent signs a payment authorization locally (e.g. EIP-712
   `transferWithAuthorization` for USDC) and retries with the
   `PAYMENT-SIGNATURE` header.
4. Server verifies + settles — usually via a **facilitator** so your server
   never runs blockchain infrastructure — then returns `200 OK` with the
   resource and a `PAYMENT-RESPONSE` receipt.

Key properties: **stateless** (no prior relationship), **self-describing**
(the 402 tells the agent the price), **non-custodial** (agent signs, funds
move only at settlement).

### Minimal FastAPI seller (testnet)

```python
from fastapi import FastAPI
from x402.http import FacilitatorConfig, HTTPFacilitatorClient, PaymentOption
from x402.http.middleware.fastapi import PaymentMiddlewareASGI
from x402.http.types import RouteConfig
from x402.mechanisms.evm.exact import ExactEvmServerScheme
from x402.server import x402ResourceServer

app = FastAPI()
NETWORK = "eip155:84532"  # Base Sepolia

server = x402ResourceServer(HTTPFacilitatorClient(FacilitatorConfig(url="https://x402.org/facilitator")))
server.register(NETWORK, ExactEvmServerScheme())

routes = {
    "GET /report": RouteConfig(
        accepts=[PaymentOption(scheme="exact", pay_to="0xYourAddress",
                               price="$0.001", network=NETWORK)],
        mime_type="application/json",
        description="Paid weather report",
    )
}
app.add_middleware(PaymentMiddlewareASGI, routes=routes, server=server)

@app.get("/report")
def report():
    return {"report": "sunny"}
```

Unauthenticated calls get `402`; retry with a signed payment gets `200`.
Full walkthrough, schemes, and header details:
[references/x402.md](references/x402.md). Runnable version:
`scripts/demo_x402_fastapi.py`.

## Rules that matter

- **Never move money on model say-so.** Any spend must pass a code-level
  policy check before a key signs — see the companion
  `agent-wallet-spend-policy` skill.
- **Price before work.** The 402 response must state exact requirements;
  never do billable work before payment is verified (except explicitly
  metered `upto` flows, where you settle actual usage ≤ authorized max).
- **Facilitators verify and settle; they don't hold funds.** Use a public
  facilitator for tests; pick one deliberately for mainnet.
- **On-chain settlement is final — no chargebacks.** Controls must be
  preventive, not remedial: caps, allowlists, replay protection (nonces +
  validity windows are built into the protocol).
- **AP2 authorizes, it does not settle.** Compose AP2 mandates with x402
  settlement when you need both authority and money movement
  ([references/ap2.md](references/ap2.md)).

## Demo

```bash
pip install "x402[fastapi,httpx,evm]" uvicorn
python scripts/demo_x402_fastapi.py   # serves GET /report; expect 402 without payment
```
