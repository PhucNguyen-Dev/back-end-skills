---
name: payments-ledger-reconciliation
description: Double-entry ledger and money reconciliation for payment backends — journal entries, append-only postings, three-way reconciliation between ledger, settlement receipts and processors, break workflows, disputes and chargebacks. Use when recording money movement, building a ledger next to billing code, reconciling Stripe/x402 settlements, or investigating payment drift.
license: MIT
compatibility: demo uses Python standard library only.
metadata:
  version: "1.0.0"
  domain: ai-payment-infra
---

# Payments Ledger & Reconciliation

Metering tells you what was used, billing tells you what you charged — the
ledger tells you what you actually **have and owe**. It is the system of
record auditors, banks, and finance teams trust; everything else is a
sub-ledger feeding it.

## The rules

1. **Double-entry or nothing.** Every money movement is ≥2 postings whose
   debits equal credits. An unbalanced entry is rejected, not "fixed later".
2. **Append-only.** Never UPDATE or DELETE a posting. Corrections are new
   entries that reverse the mistake — history must stay readable.
3. **Idempotent by event id.** Replayed webhooks, settlement callbacks, and
   queue redeliveries post exactly once.
4. **Money is integers.** Store minor units (cents) in `int`. Floats round
   wrong; bigints don't.
5. **Reconcile automatically, daily.** Ledger vs processor statement vs
   bank/on-chain records. Breaks alert on day one — they never age quietly.
6. **API status ≠ money settled.** `"status": "paid"` in your database means
   nothing until the source of truth agrees. Post revenue when cash or a
   collectible claim actually moves.
7. **Finality changes the playbook.** Card rails reverse (chargebacks);
   chains don't (manual refunds only). Both paths are code, not runbooks.

## Architecture

```
sources                     normalize+dedupe        journal            control
─────────                   ───────────────         ───────            ───────
x402 settlement receipts ─┐
Stripe webhooks ──────────┼─► event store ──► post() ──► entries        trial balance
bank statements ──────────┤   (idempotent)   balanced  postings(appl.)   ▲
on-chain tx watch ────────┘                       │                     │
                                                   └─► reconciliation ───┘
                                                        │ match by ref/amount/window
                                                        ▼
                                                  breaks queue → owner → resolve
```

## Starter chart of accounts

| Code | Account | Normal side |
| --- | --- | --- |
| 1000 | stablecoin cash (custody) | debit |
| 1100 | processor receivable (Stripe payout pending) | debit |
| 1200 | customer credits (prepaid balances) | debit |
| 2000 | payables (to facilitators/validators) | credit |
| 4000 | revenue | credit |
| 4100 | refunds & service credits (contra-revenue) | debit |
| 5000 | payment fees (network/facilitator/Stripe) | debit |

## Journal quickstart

```python
ledger.post(
    entry_id="settle_01J...",            # stable event/settlement id
    description="x402 payment received",
    postings=[                            # must balance to 0
        ("1000", +970),                   # cash up (net of fee)
        ("5000",  +30),                   # fee expense
        ("4000", -1000),                  # revenue
    ],
)
assert sum(ledger.balances().values()) == 0   # trial balance invariant
```

Full worked entries (settlement, payout, invoice, refund, agent spend):
[references/double-entry.md](references/double-entry.md).

## Three-way reconciliation

Every period, three views of the same money must agree:

| Side | Source | Matching keys |
| --- | --- | --- |
| Internal | journal entries | `entry_id`, amount, date |
| Operational | settlement receipts / Stripe events | payment_intent, tx hash |
| External | bank statement / chain explorer | reference, amount, value date |

Automate matching (exact id → amount+window fallback), classify every miss as
a break (missing-in-ledger / missing-in-source / amount-mismatch / timing),
and route breaks to an owner with an age alert. Full job design, tolerances,
and break state machine:
[references/reconciliation.md](references/reconciliation.md).

## Disputes, refunds, finality

- **Cards reverse.** Chargeback reserves, evidence deadlines, win/loss — each
  state has its own journal entry (hold, reserve release, loss).
- **Chains don't.** A settled x402 payment is final; recovery is impossible.
  Overcharges are refunded deliberately, and spend policy
  (`agent-wallet-spend-policy`) is the only preventive control.
- **AI-specific claims** ("the agent over-called and burned my quota") settle
  as service credits — priced from metered usage
  (`ai-metering-billing`), posted to 4100.

Details and evidence checklist:
[references/disputes-chargebacks.md](references/disputes-chargebacks.md).

## Demo

```bash
python scripts/demo_ledger.py
```

Stdlib-only: posts balanced/idempotent entries, runs a three-way
reconciliation, detects planted breaks, self-tests on launch.

## Related skills

- Usage quantity → `ai-metering-billing` (meter feeds what to invoice)
- Agent wallet limits before signing → `agent-wallet-spend-policy`
- Taking payment in the first place → `agentic-payments-protocols`
