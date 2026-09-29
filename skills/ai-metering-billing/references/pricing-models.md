# Pricing models for AI products

## The three shapes

| Model | Formula | Revenue character | Risk |
| --- | --- | --- | --- |
| Flat rate | fixed per period | predictable | heavy users subsidized; cheap tiers abused |
| Usage-based | quantity × unit price | scales with value delivered | unpredictable for buyers; needs great metering |
| Hybrid (recommended) | base + included usage + overage | predictable floor + upside | two things to get right |

Most successful AI/API businesses run **hybrid**: a base fee that covers margin
on expected usage, included quota for simplicity, metered overage for growth.

## Unit choices

| Unit | When | Notes |
| --- | --- | --- |
| Per token (in/out separate) | LLM APIs | match your cost basis; weight output tokens higher |
| Per request/invocation | tools, endpoints | simple; pair with tiered per-model multipliers |
| Per GPU-second / compute unit | inference jobs | good when cost tracks time |
| Per outcome (per report, per image) | productized outputs | easiest for buyers to reason about |
| Credits | prepay, agent budgets | one balance, many metrics; great for agents |

Credit packs unify metrics: price credits per dollar of compute, debit by
converted cost, and expose one balance to humans *and* agents. Credits also
compose with x402 prepaid flows.

## Guardrails

- **Tie price to cost + margin, not vibes**: `unit_price = unit_cost / (1 - target_margin)`.
- **Separate cheap vs expensive endpoints** in both price and rate limit —
  never let health checks consume inference quota.
- **Lock aggregation before launch**: Stripe metered prices can't change
  `aggregate_usage` afterward.
- **Test the pathological user**: an uncapped free tier or an off-by-1000 unit
  is a cash burn. Model worst case before go-live.
- **Publish the math**: a pricing page formula ("$X per 1M output tokens")
  builds more trust than an opaque "credits".

## Encoding a hybrid plan

```python
plan = {
    "name": "pro",
    "base_monthly_usd": 49,
    "included": {"llm_tokens_out": 10_000_000, "api_calls": 50_000},
    "overage": {"llm_tokens_out": 0.000006, "api_calls": 0.0002},  # per unit
    "rate_limits": {"rpm": 600, "concurrent_inference": 8},
}
```

- Included quota → enforced as counters; overage → flagged events, billed at
  period end via the metering pipeline.
- `rate_limits` are a **product feature**, not just protection: show them in
  the plan table and in `429` headers so upgrade paths are obvious.

## Agent-specific notes

- Agents buy **sub-dollar, high-frequency** units (x402 territory) or
  **budgeted credit packs** with hard caps — see `agent-wallet-spend-policy`.
- For agent customers, expose usage and remaining budget as structured data
  (API/MCP), not only a dashboard: agents budget better with machine-readable
  numbers.
- Dynamic pricing (server quotes at request time) must return an estimate
  up front so the agent can decide; x402 `upto` + estimate fields serve this.
