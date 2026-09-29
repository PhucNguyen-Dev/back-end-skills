---
name: agent-wallet-spend-policy
description: Control how AI agents spend money — wallet and key custody, per-transaction and session spend limits, counterparty allowlists, human approval thresholds, and tamper-evident audit logs. Use when an agent holds a payment key, before signing any agent-initiated payment, or to design spend limits enforced in code rather than prompts.
license: MIT
compatibility: Reference implementation is Python standard library only; runs offline with no dependencies.
metadata:
  version: "1.0.0"
  domain: ai-payment-infra
---

# Agent Wallet & Spend Policy

An agent with an unconstrained key is an unconstrained spender. On stablecoin
rails settlement is **final — no chargebacks** — so every control must be
preventive: it must hold *before* the payment goes out.

## Non-negotiables

1. **Enforce policy outside the model.** Prompts are advisory; a jailbreak or
   a hallucination must not be able to spend. The check lives in code, next to
   the signing step, and runs on every payment regardless of what the model
   says.
2. **Deny by default.** A payment request that fails validation — missing
   fields, unknown counterparty, price above ceiling — is rejected, never
   "approved with a warning".
3. **The key never enters the model's context.** No private keys in prompts,
   logs, or tool outputs. Signing happens in code (or KMS/HSM/MPC) using
   material the model cannot read.
4. **Every payment is logged before it is signed** to a tamper-evident audit
   trail; retrofitting audit after an incident has none of the benefit.

## The pre-sign check

Single choke point: all payments — x402 payloads, wallet transfers, card
authorizations — pass through one function.

```python
def authorize(request: PaymentRequest, policy: Policy) -> Decision:
    reasons = []
    if request.amount > policy.per_tx_limit:
        reasons.append("per_tx_limit")
    if request.payee not in policy.allowlist:
        reasons.append("payee_not_allowed")
    if spent_today(request.agent_id) + request.amount > policy.daily_limit:
        reasons.append("daily_limit")
    if request.amount > policy.human_approval_threshold:
        return pending_human_approval(request, reasons)
    if reasons:
        return Decision.deny(reasons)      # deny by default
    return Decision.approve()
```

Mirror this in client hooks where they exist (e.g. x402's
`onPaymentRequested` in MCP bridges): compare amount, currency, network,
facilitator, expected tool call, and session budget **before the wallet
signs**.

## Core controls

| Control | Question it answers |
| --- | --- |
| Per-transaction cap | Can one bad call drain the wallet? |
| Session / daily budget | Can a loop drain it slowly? |
| Counterparty allowlist | Is this address/domain even supposed to be paid? |
| Human approval threshold | Above $X, a person must click. |
| Rate / velocity limit | Is something retrying payments? |
| Network & asset allowlist | Only Base + USDC? No unknown tokens. |
| Replay guards | Nonce/validity windows (x402 core does this; verify receipts) |

Full patterns: [references/spend-policy.md](references/spend-policy.md).

## Key custody

Pick custody deliberately — it defines what "policy" can even enforce:

| Option | Trust model | Fit |
| --- | --- | --- |
| Raw key on disk | you | prototypes only |
| KMS/HSM signing | cloud | production default |
| MPC / smart wallet with rules | provider | policy enforced at wallet layer |
| Session keys with scoped limits | delegated | agents: short-lived, capped sub-keys |

Details, rotation, and secret hygiene:
[references/wallets-keys.md](references/wallets-keys.md).

## Audit & compliance

- Append-only log: who (agent id), what (amount/payee/metric), why (mandate or
  budget reference), decision + reasons, timestamp, tx hash.
- Tamper-evident: hash-chain or sign entries; keep them exportable for anyone
  with subpoena power.
- Regulation exists: GENIUS Act (US), MiCA (EU) cover the stablecoins agents
  settle in. Notes: [references/audit-compliance.md](references/audit-compliance.md).

## Demo

```bash
python scripts/demo_spend_policy.py    # stdlib only, self-tests on launch
```

Covers: allowlist, per-tx/daily caps, human-approval threshold, deny-by-default
on malformed requests, and an append-only audit trail.

## Related skills

- Payment mechanics → `agentic-payments-protocols`
- Budgets backed by meters/invoices → `ai-metering-billing`
