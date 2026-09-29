# Disputes, Refunds & Chain Finality

Two worlds with opposite physics: card rails reverse, blockchains don't.
Your ledger and code must handle both.

## Card world (Stripe): money can come back

Lifecycle: `inquiry → chargeback (dispute) → evidence → resolution`.

```
charge.dispute.created   → hold funds:   debit 1150 dispute-hold   credit 1000 cash
charge.dispute.won       → release hold: debit 1000 cash            credit 1150 dispute-hold
charge.dispute.lost      → realize loss: debit 4100 dispute-loss    credit 1150 dispute-hold
```

- Stripe **withdraws the disputed amount immediately** (reserve), so mirror
  it same-day or your cash reconciliation breaks.
- Evidence deadlines are hard (often 7–21 days). Missing one = automatic
  loss. Track `charge.dispute.*` webhooks, never poll.
- Notorious for AI products: *"agent didn't deliver / unauthorized agent
  spend."* Your evidence pack must show authority + delivery (below).

## Stablecoin world (x402 / on-chain): final means final

- A settled x402 payment **cannot be reversed**. No issuer, no arbitration.
- Overcharge recovery = a *deliberate new payment* (refund transaction);
  mistaken transfers to the wrong address are unrecoverable.
- Therefore prevention is the whole game: spend policy caps, payee
  allowlists, human approval thresholds — all *before* signing
  (`agent-wallet-spend-policy`). There is no after.
- Cross-check with regulation: stablecoins used like money fall under
  GENIUS Act (US) / MiCA (EU) obligations — diligence your issuers and
  reserve attestations (context for your compliance team, not code).

## Refunds & service credits (both worlds)

Usage is consumed but disputed on quality ("agent hallucinated and burned
2M tokens"):

1. Price the make-good from actual metered usage (`ai-metering-billing`).
2. Post a service credit: `debit 4100 credits  / credit 1000 cash` (or
   `credit 1200 customer-credits` if held as balance).
3. Never edit or delete the original revenue entry — the sale happened;
   the credit is the story of what followed.

## Evidence checklist (what actually wins cases)

| Proof | Where it lives |
| --- | --- |
| Authority to spend (mandate/policy decision) | AP2 mandate or policy-check log + approval hash |
| What was delivered | request id → model → token counts (meter) |
| What was charged | invoice / usage record, idempotency keys |
| What was paid | settlement id + tx hash / payment_intent |
| Terms acceptance | signed ToS version + timestamp, clickwrap log |
| Idempotent replay behavior | event-store rows proving no double-charge |

Bind these with **one correlation id per purchase flow** across meter →
invoice → settlement → ledger `entry_id`. When a dispute arrives you export
a timeline, not a treasure hunt.

## Reserve & cash planning

- Card processors hold rolling reserves and dispute reserves — model them
  as real accounts (1160 reserve-hold), not as "Stripe is missing money".
- Never spend 100% of stablecoin cash outflow capacity while open disputes
  exist; keep a buffer ≥ open-hold total (few disputes need it, but hitting
  zero while funds are frozen turns a $50 dispute into a crisis).
