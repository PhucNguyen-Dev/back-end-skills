# Metering pipeline — durable, idempotent, near-real-time

The meter sits between your API/model gateway and billing. Its job: every
billable event is counted **exactly once**, survives restarts, and is visible
to customers before the invoice arrives.

## Event contract

```json
{
  "event_id": "0193f2c1-...-...",      // globally unique, generated at source
  "idempotency_key": "org_42:req_abc:attempt_1",
  "customer_id": "cus_…",              // or org/api-key id
  "metric": "llm_tokens_out",          // namespaced: llm_tokens_in, llm_tokens_out, api_call, gpu_seconds
  "quantity": 1280,
  "model": "some-large-model",
  "unit_price_hint": "0.000008",       // optional; pricing stays in billing
  "ts": "2026-09-29T12:00:00Z",
  "labels": {"endpoint": "/v1/completions", "key_id": "sk_live_…"}
}
```

- **`event_id` / `idempotency_key`** is the dedup token. Ingestion rejects
  duplicates (unique index), so a producer retry is harmless.
- Emit at the point of consumption (post-inference), not at request receipt —
  a failed call shouldn't bill.
- Never block the billable response on metering: write to the queue, return.

## Ingestion → aggregation

```
producer ──► queue/table (unique event_id) ──► aggregator ──► period totals
                          ▲                        │
                     replay/backfill               ├─► billing flush (increment)
                                                   ├─► quota service
                                                   └─► customer-facing usage API
```

- Aggregation window: per customer × metric × billing period (hourly rollups
  for dashboards are fine; keep raw events for the period for disputes).
- **Idempotent aggregation**: reprocessing an event must not change totals —
  dedup at ingestion, not by "subtract and re-add".
- Report to Stripe in batches with `action="increment"` so a whole-batch retry
  is safe.

Reference implementation: `scripts/demo_metering.py` (SQLite, stdlib) —
unique-index ingestion, period totals, retry-safe flush preview.

## Quotas & rate limiting

| Concern | Approach |
| --- | --- |
| Enforcement point | API gateway / middleware, keyed by API key or customer |
| Algorithm | token bucket or sliding window; **atomic check-and-add** (Lua script / transaction) — non-atomic ZREMRANGEBYSCORE+ZADD races under concurrency |
| Response | `429` + `Retry-After` + `X-RateLimit-Limit` / `-Remaining` / `-Reset` |
| Granularity | separate counters per expensive class (inference vs cheap endpoints) |
| Free tier | hard rate limits + abuse detection; an uncapped free tier is free compute |

## Quota exhaustion

Prefer, in order:

1. **Throttle** at the soft limit (degraded rate, `Retry-After`).
2. **Overage billing** if the plan defines it — with proactive notification
   *before* the customer is surprised.
3. **Hard cutoff** only as the last safety rail (plan explicitly forbids
   overage) — and return a structured 429 with an upgrade path, never a 500.

Never silently drop requests at the limit; production systems must see a
clean, retryable signal.

## Accuracy & operations

- **Cardinality guard**: cap distinct label values (model names, endpoints);
  unbounded label sets are the classic metering outage.
- **Backfill**: raw events are replayable — a bug in aggregation is fixed by
  re-running, not by apologizing.
- **Daily reconciliation**: sum(raw events for period) == sum(reported usage
  records). Alert on drift > tolerance.
- **Customer-visible usage**: expose the same numbers you bill from, near
  real-time (cached rollup). Disputes drop when users see what you see.
- **Latency tolerance**: billing is eventually consistent; quotas should be
  checked against the freshest local rollup (seconds), not the billing flush
  (hours).

## Anti-patterns

| Don't | Do instead |
| --- | --- |
| Count in an in-process dict | durable queue/table with unique key |
| Report usage per request | batch flush on a schedule |
| `action="set"` on retries | `action="increment"` + idempotency keys |
| Bill from gateway logs alone | dedicated metering service; logs are incomplete/late |
| One shared rate limit for all endpoints | weight/separate by cost |
| Drop events when billing is down | buffer durably, flush late; usage never disappears |
