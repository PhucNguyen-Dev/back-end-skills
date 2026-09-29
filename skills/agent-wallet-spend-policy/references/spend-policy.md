# Spend policy — controls that hold before money moves

## Threat model (short)

- **Model error/hallucination**: agent pays the wrong amount or party.
- **Prompt injection**: attacker-controlled content tricks the agent into
  paying them.
- **Runaway loop**: agent retries/repeats a paid action.
- **Stolen key**: wallet material exfiltrated from the host.
- **No recourse**: stablecoin settlement is final; there is no dispute process
  to hide behind. Controls are preventive or they are theater.

## The policy object

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class SpendPolicy:
    agent_id: str
    per_tx_limit_atomic: int          # e.g. 10_000_000 = 10 USDC (6 decimals)
    session_limit_atomic: int
    daily_limit_atomic: int
    human_approval_threshold_atomic: int   # >= this requires a person
    allowlisted_payees: frozenset[str]     # addresses / merchant ids
    allowed_networks: frozenset[str]       # {"eip155:8453"}
    allowed_assets: frozenset[str]         # {"USDC"}
    allowed_merchants: frozenset[str] = field(default_factory=frozenset)
```

Store policy as config reviewed like code (PR review, versioned), not as
free-text in a system prompt.

## Check order (cheap → expensive → human)

1. **Schema validation** — required fields present, amount parses, positive,
   correct units (atomic units, not floats). Malformed → deny (never guess).
2. **Static allowlists** — payee, network, asset, merchant. Deny if unknown.
3. **Velocity** — too many payment attempts in a window → deny + alert.
4. **Caps** — per-tx, then session, then daily/historical spend. All must pass.
5. **Human approval** — at/above threshold, route to approval queue with
   full context (who, what, why, expiry). Approval is bound to the exact
   payment (hash), not "approve this agent".
6. **Approve + log** — write the audit entry *before* signing.

Fail-closed: if the policy service, spend tracker, or clock is unavailable,
deny. Availability of spending is not availability of your product.

## Where to enforce

| Surface | Hook |
| --- | --- |
| x402 client / MCP bridge | `onPaymentRequested`-style callback: verify amount, network, tool, budget before `createPaymentPayload` |
| Wallet transfer API | middleware on the sign/submit function — the only function that can sign |
| Card/virtual-card issuance | per-card limits at issuance + merchant controls at the network |
| AP2 | translate `AmountRange`/`AllowedPayees` mandate constraints into the same checks |

One choke point per payment type; all roads lead to `authorize()`.

## Session budgets

```python
class SessionBudget:
    def charge(self, amount_atomic: int) -> None:
        # atomic check-and-add; concurrent calls must not both pass
        ...
```

- Pre-authorize a session cap (MPP-style "open a tab" or x402 `upto` max),
  decrement locally on each payment, settle/verify receipts to stay honest.
- The model gets to see **remaining budget** as data (helps it plan), but it
  cannot write it.
- Reset policy: sessions are short-lived; expired session keys stop working.

## Approval workflows

- Queue with context: amount, payee, purpose, linked task/mandate, request age.
- Bind approval to a digest of the payment parameters; any change invalidates.
- Time-box approvals (short TTL) and never re-use one approval for a repeat.
- Record approver identity in the audit log.

## Common mistakes

| Mistake | Consequence |
| --- | --- |
| Trusting the model to "only spend what's allowed" | jailbreak/injection = drain |
| Float amounts for money | rounding bugs = wrong charges; use integer atomic units |
| Allowlist the payee but not the network/asset | paid wrong chain/token |
| Cap per-transaction only | slow bleed via repetition |
| Approvals granted to the agent, not the payment | replayable authority |
| Logging after signing | an incident erases its own evidence |
| Fail-open when tracker is down | outage becomes a payout |
