# Security Policy

## Scope

This repository is a **reference implementation and educational suite**. It
has not undergone an external security audit or certification (PCI-DSS,
SOC 2). Do not deploy it to handle real funds without your own review.

Report suspected vulnerabilities privately via GitHub → *Security* →
*Report a vulnerability* (or open an issue if private reporting is unavailable
and the issue is not fund-affecting).

## Key & secret handling

- **Environment private keys are development-only.** `WALLET_PRIVATE_KEY`
  exists for local/testnet demos. Production signing must go through a
  KMS/HSM/MPC signing service behind the `Signer` interface
  (`examples/e2e-paid-api/app/signing.py`).
- Never place keys, seeds, or live API keys in prompts, logs, tool outputs,
  or this repository. CI uses no secrets; live tests are opt-in via
  environment variables.
- Rotate any key that has ever been printed, committed, or shared.
- The default payee `0x000000000000000000000000000000000000dEaD` and all
  default addresses are placeholders (testnet).

## Payment-specific posture

- **No card data (PAN) touches this code** — payments are stablecoin (x402)
  or billed through Stripe, which keeps you in scope of a reduced PCI
  questionnaire (SAQ-A territory) *only if that stays true*. Adding card
  collection changes your compliance scope; get counsel.
- **On-chain settlement is final — there are no chargebacks.** Spend policy
  must be preventive and enforced in code before signing
  (`agent-wallet-spend-policy` skill), not corrective.
- **Webhook signatures must be verified** against the raw body
  (`app/webhooks.py` shows the pattern). Never trust unsigned payloads.
- Stablecoins used for settlement are regulated instruments (GENIUS Act in
  the US, MiCA in the EU). This is context, not legal advice.

## Dependency & supply chain

- Application dependencies are **pinned** (`requirements.txt`); Dependabot
  proposes updates; CI validates on Ubuntu + Windows before merge.
- Skills are validated by the official
  [`skills-ref`](https://github.com/agentskills/agentskills) validator plus
  `scripts/validate_skills.py` on every push.

## Secure defaults demonstrated

| Control | Where |
| --- | --- |
| Deny-by-default pre-sign policy | `app/policy.py` |
| Idempotent metering (no double-bill) | `app/meter.py` |
| Raw-body webhook verification + replay protection | `app/webhooks.py` |
| Hash-chained append-only audit log | `skills/agent-wallet-spend-policy/scripts/demo_spend_policy.py` |
| Testnet-first defaults, facilitator over self-custody | `app/server.py` |
