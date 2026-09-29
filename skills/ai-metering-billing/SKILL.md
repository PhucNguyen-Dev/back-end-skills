---
name: ai-metering-billing
description: Meter AI usage and bill for it — token/invocation counters, durable usage pipelines, Stripe metered billing and usage records, webhook state machines, quotas and overage. Use when designing usage-based pricing, reporting API or model usage to Stripe, enforcing quotas, or fixing billing accuracy and double-charge bugs.
license: MIT
compatibility: Python examples use stripe SDK (pip install stripe) and stdlib SQLite for the demo; Stripe API keys needed only for live reporting.
metadata:
  version: "1.0.0"
  domain: ai-payment-infra
---

# AI Metering & Billing

Turn AI usage into revenue without charging for usage you cannot prove.

## The rules

1. **Meter before you bill.** Instrument every billable event with a durable,
   idempotent counter *before* enabling paid tiers. Lost events = lost revenue
   or customer disputes.
2. **Usage records are idempotent.** Retries, duplicate webhooks, and
   reprocessed queues must never double-count. Use an idempotency key on every
   report.
3. **Batch, don't stream.** Report usage hourly/daily, not per request —
   per-request reporting hammers the Stripe API and risks rate limits.
4. **Webhooks are the source of truth.** Payment/subscription state comes from
   signed webhooks, not polling or your local copy.
5. **Throttle, don't hard-cut.** At quota: enforce `429` + `Retry-After`, or
   bill overage — never silently break a customer's production.
6. **Durable queue, not a dict.** In-memory buffers lose a billing period on
   restart. Write events to a queue/DB before aggregating.

## Architecture

```
API / model call
   │  emit event {customer, metric, quantity, idempotency_key}
   ▼
durable queue (SQS/Kafka/SQLite…)  ← write-ahead, replayable
   │
   ▼
aggregator  →  per-period totals
   │
   ├─► Stripe usage records (action="increment", batched)
   ├─► quota check → 429 / overage flag
   └─► analytics / invoicing detail
```

## Stripe flow (quickstart)

```python
import stripe
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

# 1. One-time setup: product + metered price
price = stripe.Prices.create(
    product=product_id, currency="usd",
    recurring={"interval": "month", "usage_type": "metered",
               "aggregate_usage": "sum"},
    unit_amount=200,              # $0.002 per unit (cents, per_unit scheme)
    billing_scheme="per_unit",
)

# 2. Usage reporting — always action="increment" (retry-safe)
def flush(period_totals: dict[str, int]) -> None:
    for sub_item_id, qty in period_totals.items():
        if qty <= 0:
            continue
        stripe.SubscriptionItem.create_usage_record(
            sub_item_id,
            quantity=qty,
            timestamp=int(time.time()),
            action="increment",     # NEVER "set" — retries silently under-bill
            idempotency_key=f"usage:{sub_item_id}:{period}:{qty}"[:255],
        )
```

Full walkthrough (webhooks, subscription lifecycle, dunning):
[references/stripe-metering.md](references/stripe-metering.md).

## Quota enforcement

Tie rate limits to paid tiers at the gateway: token bucket or sliding window
per API key, always with headers:

```
HTTP/1.1 429 Too Many Requests
Retry-After: 30
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1735689600
```

Weight quotas by endpoint cost — a token-heavy inference endpoint and a health
check must not share one counter. Details:
[references/metering-pipeline.md](references/metering-pipeline.md).

## Pricing models

| Model | Shape | Use |
| --- | --- | --- |
| Flat rate | fixed monthly tier | predictable tiers, seats |
| Usage-based | per token/call/unit | pure API businesses |
| Hybrid | base fee + included usage + overage | most AI products (predictable + scalable) |
| Credit packs | prepaid balance debited per call | prepay, agent budgets, x402 hybrids |

Pick and encode the model before creating prices — `aggregate_usage` cannot be
changed after a metered price is created (create a new price + migrate).
Details: [references/pricing-models.md](references/pricing-models.md).

## Demo

```bash
pip install stripe          # stripe optional; demo runs offline without it
python scripts/demo_metering.py
```

Offline demo: ingests duplicate-prone events into SQLite, aggregates
idempotent per-period totals, prints a Stripe-shaped usage flush. With
`STRIPE_API_KEY` set, the flush becomes a real API call.

## Related skills

- Charging per HTTP call → `agentic-payments-protocols` (x402 `upto`)
- Pre-sign spend limits for agents → `agent-wallet-spend-policy`
