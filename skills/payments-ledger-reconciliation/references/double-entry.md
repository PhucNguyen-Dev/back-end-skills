# Double-Entry Ledger Design

## Account types and normal balances

| Type | Increases with | Example |
| --- | --- | --- |
| Asset | debit | stablecoin cash, processor receivable |
| Liability | credit | customer credits, payables |
| Equity | credit | retained earnings |
| Revenue | credit | usage revenue, subscription revenue |
| Expense | debit | network fees, dispute losses |

**Normal balance** = the side that increases the account. A trial balance
means `sum(all postings) == 0` — if it isn't zero, something was mutated or
lost; treat it as a P0.

## Worked entries

Money example: $10.00 payment (1000 cents), 30 cent fee.

**1. x402 payment settled (cash net of fee lands immediately)**

```
entry: settle_01J   x402 payment received, tx 0xabc
  debit  1000 cash            +970
  debit  5000 fees             +30
  credit 4000 revenue         -1000
```

**2. Stripe charge, later paid out (two-step: receivable → cash)**

```
entry: pi_3Pxyz   Stripe charge
  debit  1100 processor-receivable +1000
  credit 4000 revenue              -1000

entry: po_1Mnop   Stripe payout received
  debit  1000 cash                   +970
  debit  5000 fees                    +30
  credit 1100 processor-receivable   -1000
```

**3. Invoice issued (revenue recognized on accrual)**

```
entry: inv_1042   September invoice
  debit  1100 accounts-receivable  +25000
  credit 4000 revenue              -25000
```

**4. Refund / service credit (contra-revenue, never erase the sale)**

```
entry: re_9ab    refund for over-allocation
  debit  4100 refunds-and-credits  +1000
  credit 1000 cash                 -1000
```

**5. Agent spends from your custody wallet (liability decreases)**

```
entry: pol_55    policy-approved agent payment
  debit  2000 payables/facilitator  +500
  credit 1000 cash                  -500
```

## Schema sketch

```sql
CREATE TABLE entries (
  entry_id    TEXT PRIMARY KEY,      -- stable idempotency key (event/tx id)
  occurred_at TIMESTAMP NOT NULL,    -- when money moved (not when you saw it)
  recorded_at TIMESTAMP NOT NULL DEFAULT now,
  source      TEXT NOT NULL,         -- x402 | stripe | bank | manual
  description TEXT
);

CREATE TABLE postings (
  entry_id  TEXT REFERENCES entries(entry_id),
  account   TEXT NOT NULL,
  amount    INTEGER NOT NULL,        -- minor units, signed: +debit -credit
  CHECK (amount <> 0)
);

-- invariant enforced at write time: SUM(amount) per entry_id == 0
```

## Implementation rules

1. **`post()` is one transaction**: insert entry + all postings, or none.
   Reject unbalanced input before touching the DB.
2. **Idempotency**: `INSERT entry_id` first; a duplicate key means replay —
   return success without posting (webhook retries are normal).
3. **Balances are queries, not columns.** `SELECT account, SUM(amount)
   FROM postings GROUP BY account`. If you cache a balance, it is derived
   cache — rebuildable from history.
4. **Corrections are reversal entries**: post the mirror image with a new id
   referencing the original. `UPDATE postings` is forbidden by app role
   (grant read-only after write).
5. **Value time vs record time**: `occurred_at` (money moved) drives
   accounting periods; `recorded_at` drives debugging. Late events post to
   the period they *occurred in*; reopen-period handling is explicit.
6. **Split multi-leg flows atomically**: a settlement + fee + revenue is one
   entry with three legs — never three independent entries that could
   half-apply.

## Common bugs

| Bug | Symptom | Fix |
| --- | --- | --- |
| Float money | balances drift by ±1 cent | integer minor units everywhere |
| Revenue on API 200 | "revenue" for unpaid calls | post on settlement/accrual event only |
| Netting | fee hidden inside cash line | separate 5000 leg — auditors ask |
| Mutable history | audit impossible | append-only + reversal entries |
| Double webhook | 2× revenue | entry_id idempotency |
