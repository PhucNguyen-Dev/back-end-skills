# MPP and ACP — sessions and merchant checkout

## MPP (Machine Payments Protocol)

Co-authored by Tempo and Stripe; launched March 2026 with Tempo mainnet.
Settlement layer for machine-to-machine spending **with a session model**.

**Core idea:** instead of settling every request, an agent pre-authorizes a
spending limit ("open a tab"), consumes continuously, and all payments within
the session batch-settle. Stripe describes it as "OAuth for money."

- Uses HTTP `402` with `WWW-Authenticate: Payment` /
  `Authorization: Payment` headers.
- Supports fiat cards **and** stablecoins on the same endpoints (Visa
  contributed card specs); Stripe merchants can accept via PaymentIntents.
- Backwards-compatible: MPP clients can consume existing x402 services.
- Current tooling: `mppx` SDK; runs on Tempo today, spec is rail-agnostic.
- Caveat: no neutral standards body yet (unlike x402/Linux Foundation and
  AP2/FIDO); youngest of the protocols.

**Use MPP when:** per-request settlement is too chatty (thousands of calls per
session), you need fiat + crypto on one endpoint, or you want Stripe's
merchant/compliance tooling behind machine payments.

## ACP (Agentic Commerce Protocol)

Created by OpenAI + Stripe. Standardizes **agent → merchant checkout**: how a
shopping agent discovers products, assembles a cart, and completes a purchase
at a conventional merchant — fiat rails (cards, digital wallets) via Stripe.

- ACP handles the purchase flow; it designates AP2 as its payment/authority
  method rather than inventing its own.
- `SharedPaymentTokens` from ACP can ride inside MPP sessions.

**Use ACP when:** an agent is buying goods/services from a store (the
"shopping agent" case), not paying for API calls.

## Quick selection vs the others

| Need | Protocol |
| --- | --- |
| Pay for one HTTP call, no relationship | x402 |
| Cap an agent's session spend, settle in batch | MPP |
| Buy from a merchant storefront | ACP (+ AP2) |
| Prove user authority over any of the above | AP2 |

A single purchase can traverse all layers: MCP (tools) → UCP/ACP (commerce
flow) → AP2 (authority) → MPP/x402 (settlement).
