# Reconciliation: Ledger ↔ Operations ↔ External Sources

Reconciliation is the control that proves the ledger is right. Skip it and
every number downstream (pricing, payouts, taxes, investor reports) is
unverified.

## The three sides

| Side | Holds | System of record for |
| --- | --- | --- |
| Internal | journal entries | what you *believe* happened |
| Operational | settlement receipts, Stripe/payment events | what payment processors say happened |
| External | bank statements, chain activity | what actually moved |

Three-way: each operational record matches exactly one journal entry AND one
external line. Pairwise-only matching (ledger↔processor) misses the case
where both are wrong together.

## Matching strategy (in order of confidence)

1. **Exact key**: `payment_intent`, settlement id, tx hash, invoice id →
   O(1) join, no ambiguity.
2. **Amount + counterparty + window**: $970 from Stripe between 14:00–15:00
   → candidate set; require 1:1 within the set.
3. **Aging report**: anything unmatched after N periods escalates.

Never match on amount alone when duplicates are possible (subscriptions make
identical amounts routine).

## Timing windows (expected "timing" breaks)

| Source | Normal lag | Notes |
| --- | --- | --- |
| Stripe payout | 2–7 days (rolling reserve possible) | charge sits in 1100 until paid out |
| x402 settlement | seconds–minutes | facilitator settles at request time |
| On-chain confirmation | seconds (L2) | value date = confirmation, not broadcast |
| Bank wire/ACH | 1–3 business days | cutoff times create day-boundary breaks |

A break inside its window is **timing**, state=`open(timing)` — it resolves
itself; outside the window it escalates to `investigating`.

## Break taxonomy & state machine

```
break types: missing-in-ledger | missing-in-source | amount-mismatch | timing
states:      open ──auto-match/late-post──► resolved
              │
              └──aged or amount-mismatch──► investigating ──root-cause──► resolved
                                              │                        (or: written-off
                                              └──error found──► fix via reversal entry    with approval)
```

- **missing-in-ledger**: money moved, no posting → post late entry
  (`occurred_at` backdated), root-cause the listener gap.
- **missing-in-source**: you posted something the source denies → likely
  stale/phantom status; reverse it.
- **amount-mismatch**: fee/split differences are code bugs (leg missing) —
  reverse + repost correct entry.
- **written-off** requires a second approver; silent resolution of
  amount-mismatches is how fraud hides.

## Daily job (shape)

```python
def reconcile(day: date) -> Breaks:
    entries  = journal.by_period(day)
    ops      = fetch_receipts(day)          # x402 + Stripe events
    external = fetch_statements(day)        # payouts + chain tx

    matched, breaks = match(entries, ops, key=exact_key)
    matched, breaks += match(breaks, external, key=amount_window)

    for b in breaks:                        # classify + route
        b.state = "timing" if within_window(b) else "open"
        alert_if_aged(b, threshold_hours=24)
    return breaks
```

Run it idempotently (same day re-run → same result); the job is derived data.

## Metrics to alert on

- `break_count` and `break_amount_minor` by type — any non-zero >24h.
- **Trial-balance violations** (sum ≠ 0) — page immediately, means mutation
  or lost postings.
- Unmatched Stripe payouts older than payout window; chain tx seen but not
  posted; journal entries with no external confirm after settlement SLA.
- Ledger-vs-subledger drift: meter/invoice totals vs revenue account per
  period (ties this skill to `ai-metering-billing`).

## Period close

1. All breaks for the period resolved or explicitly written off.
2. Trial balance zero; sub-ledger tie-outs done (revenue = invoices + direct
   settlements ± credits).
3. Lock the period (inserts rejected for locked dates) — later corrections
   belong to the current period via reversal.
4. Export trial balance for accounting/tax — the first thing external
   auditors request.
