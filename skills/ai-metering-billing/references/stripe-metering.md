# Stripe metered billing — full flow

Server-side only: `pip install stripe`. Secret key never leaves the backend;
browser flows use Stripe.js/Elements separately.

## 1. Catalog setup

```python
import stripe
stripe.api_key = os.environ["STRIPE_SECRET_KEY"]

product = stripe.Products.create(name="AI API", metadata={"tier": "pro"})

# Metered, per-unit price: $0.002 per reported unit
price = stripe.Prices.create(
    product=product.id,
    currency="usd",
    recurring={
        "interval": "month",
        "usage_type": "metered",
        "aggregate_usage": "sum",   # last_during_period | last_ever | max | sum
    },
    unit_amount=200,                # cents; use unit_amount_decimal for < $0.01
    billing_scheme="per_unit",
)
```

- `aggregate_usage` is **immutable after creation** — choosing wrong means a
  new price + subscriber migration. Decide before production.
- `unit_amount_decimal` exists for sub-cent unit prices (AI calls often need it).
- Plans are Products + Prices; mirror them locally if you render plans in UI
  (a `sync-plans` command from Stripe → local tables keeps them honest).

## 2. Subscribe the customer

```python
subscription = stripe.Subscriptions.create(
    customer=customer.id,
    items=[{"price": price.id}],
    payment_behavior="default_incomplete",
    expand=["latest_invoice.confirmation_secret"],
    metadata={"org_id": org_id},
)
# Store subscription.id + the metered subscription_item.id — you need the
# latter as the usage-record target.
```

## 3. Record usage (batched, idempotent)

```python
def report_usage(sub_item_id: str, qty: int, period_key: str) -> None:
    stripe.SubscriptionItem.create_usage_record(
        sub_item_id,
        quantity=qty,
        timestamp=int(time.time()),
        action="increment",   # retry-safe: increments accumulate
        idempotency_key=f"{sub_item_id}:{period_key}:{uuid.uuid4()}"[:255],
    )
```

**Never `action="set"` for streamed usage.** A retried `set` overwrites the
period total with a stale value and silently under-bills. Use `set` only when
you genuinely mean "the total is now exactly X" (e.g. a gauge computed from
your own authoritative totals) — and even then, keys and recompute carefully.

Batch on a schedule (hourly/daily) from your aggregator, not per request.

## 4. Webhook state machine

```python
from fastapi import FastAPI, Request
import stripe

app = FastAPI()
WEBHOOK_SECRET = os.environ["STRIPE_WEBHOOK_SECRET"]
PROCESSED: set[str] = set()   # production: a stripe_event table with event.id

@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    raw = await request.body()                       # RAW bytes, never parsed
    try:
        event = stripe.Webhook.construct_event(
            raw, request.headers.get("stripe-signature", ""), WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        return {"detail": "invalid signature"}, 400

    if event.id in PROCESSED:                        # idempotent re-delivery
        return {"detail": "duplicate"}
    handle(event)                                    # fast, no long work
    PROCESSED.add(event.id)
    return {"detail": "ok"}
```

Critical points:

- **Verify with the raw body.** JSON-parsed middleware (Express/FastAPI
  defaults) corrupt the payload → signature fails. Mount the webhook route
  with raw access.
- **Return 200 fast.** Do long work after responding (queue), or Stripe times
  out and re-delivers.
- **Track `event.id`** for idempotency — Stripe delivers at-least-once.
- **Handle the subscription lifecycle**, not just success:
  `customer.subscription.updated/deleted`, `invoice.paid`,
  `invoice.payment_failed`, `invoice.payment_action_required`.

## 5. Lifecycle & dunning

| Event | Local action |
| --- | --- |
| `invoice.payment_failed` | mark past_due, notify, escalate retry schedule |
| `invoice.paid` | clear dunning state, issue receipt |
| `customer.subscription.updated` | sync status, period, cancel_at_period_end |
| `customer.subscription.deleted` | downgrade to free, revoke paid quota |
| `payment_intent.requires_action` | SCA/3DS — surface to user, don't guess |

- Proration is **on by default** on plan changes; pass
  `proration_behavior="none"` to disable.
- Idempotency keys expire after **24h** — long-lived retries need fresh keys.
- Always pass `metadata` (org/user ids) through Checkout/sessions and
  subscriptions; it is your join key for reconciliation.

## 6. Local vs Stripe drift

Your DB is a cache; Stripe is authoritative for money. Reconcile:

- Nightly: pull open invoices + subscription status, diff against local.
- Webhook gap detection: if you never saw `invoice.paid` but Stripe says paid,
  repair from the API.
- Never mutate a local balance directly — go through your ledger/credit
  service so every change is attributable.

## Test mode

- Develop entirely in Stripe test mode; separate keys per environment.
- Forward events locally: `stripe listen --forward-to localhost:8000/webhooks/stripe`
- Test cards: `4242 4242 4242 4242` (success), `4000 0000 0000 9995`
  (insufficient funds → dunning path).
