# Wallets & keys — custody for agents

## Custody spectrum

| Model | Who holds the key | Strength | Weakness |
| --- | --- | --- | --- |
| Raw key file / env | you | simple | exfiltration = total loss; prototype only |
| Cloud KMS / HSM | provider, audited | keys never leave hardware; IAM + audit | cloud lock-in; latency per signature |
| MPC / smart contract wallet | shared/threshold | policy enforced *in the wallet* (rules, guardians) | provider dependency, on-chain complexity |
| Smart account with rules | code on-chain | spend rules are the contract, not your server | gas, upgradeability risk |
| Session keys (scoped sub-keys) | agent runtime, short-lived | blast radius = session cap | requires parent key + revocation path |

**Production default:** a parent wallet in KMS/MPC that mints **session keys**
with tight limits (amount, duration, allowlist) for each agent run. Policy
lives with the key material — an agent can only do what its key allows even if
your app layer is bypassed.

## Session keys, concretely

1. Before a run: parent derives/authorizes a sub-key with `{cap, ttl,
   allowlist, session_id}`.
2. Agent uses the sub-key for payments; app-layer `authorize()` adds
   business rules on top.
3. On completion/expiry: key invalidated; unused allowance evaporates.
4. Revoke immediately on anomaly (velocity spike, failed checks).

This mirrors how human "limited card numbers" work, and it is the single most
effective control for autonomous agents.

## Secret hygiene

- **Never** in model context: no keys in prompts, tool arguments, completions,
  or logs. If the model can see it, an injected instruction can extract it.
- Env/secret manager only; rotate on suspicion and on a schedule.
- Separate keys per environment (testnet keys never touch mainnet) and per
  agent — revocation without collateral damage.
- Signing service = narrow API (`sign(digest, policy_context)`) so every
  signature passes policy; never ship the raw key to the app tier.
- Redact addresses/keys from logs where they could aid targeting; store
  receipts/tx hashes instead.

## Buying/selling without custody of user funds

Two roles, don't confuse them:

- **Your agent pays for services** → you need signing + policy (this skill).
- **Your API gets paid** → you only need a `pay_to` address; funds settle via
  facilitator; no key custody required (x402 seller side).

If you're a platform issuing virtual cards or allowances to agents, you're a
custodian of *limits*, not funds — enforce at issuance, monitor centrally.

## Key events to audit

key.created, key.rotated, key.revoked, session_key.issued,
session_key.expired, policy.denied, policy.approved, payment.signed,
payment.settled. Each lands in the append-only trail
(see [audit-compliance.md](audit-compliance.md)).
