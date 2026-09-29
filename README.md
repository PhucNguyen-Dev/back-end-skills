# back-end-skills

[![CI](https://github.com/PhucNguyen-Dev/back-end-skills/actions/workflows/ci.yml/badge.svg)](https://github.com/PhucNguyen-Dev/back-end-skills/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![skills-ref](https://img.shields.io/badge/skills--ref-validated-4c1.svg)](https://github.com/agentskills/agentskills)

A suite of [Agent Skills](https://agentskills.io/specification) for building
**AI payment infrastructure** on the backend. Each skill teaches an agent one
route through the money stack:

| Skill | Route | Direction |
| --- | --- | --- |
| [`agentic-payments-protocols`](skills/agentic-payments-protocols/SKILL.md) | Charge for HTTP resources, pay for services as an agent | Sell to agents (x402), buy with proof of authority (AP2) |
| [`ai-metering-billing`](skills/ai-metering-billing/SKILL.md) | Meter AI usage → bill → collect | Turn token/invocation usage into revenue |
| [`agent-wallet-spend-policy`](skills/agent-wallet-spend-policy/SKILL.md) | Keys, spend caps, allowlists, audit | Let agents spend — only within policy enforced in code |
| [`payments-ledger-reconciliation`](skills/payments-ledger-reconciliation/SKILL.md) | Record money, prove balances, catch drift | Double-entry journal + three-way reconciliation + disputes |

Together: one path makes your API earn from agents, one makes your agent spend
safely, metering ties both to billing, and the ledger proves the money is
where you think it is.

## Status & scope

- **What this is:** a validated reference suite + runnable starter backend for
  AI payment infrastructure. Verified against `x402` SDK **2.24.0**, Python
  **3.11–3.14**, on CI (Ubuntu + Windows).
- **What this is not:** not audited, not certified (PCI-DSS/SOC2), not a
  substitute for a security review before handling real funds. See
  [SECURITY.md](SECURITY.md).
- The settlement integration test runs against **Base Sepolia testnet** only
  when you supply a funded key; CI runs the offline suite.

## Install

Skills use the portable `SKILL.md` spec, so they work in Claude Code, opencode,
and any spec-compliant harness.

**Claude Code (global) — also read by opencode**

```powershell
Copy-Item -Recurse skills\* "$env:USERPROFILE\.claude\skills\"
```

**opencode (global)**

```powershell
Copy-Item -Recurse skills\* "$env:USERPROFILE\.config\opencode\skills\"
```

**Project-local**: copy the skill directories into the target repo's
`.opencode\skills\`, `.claude\skills\`, or `.agents\skills\`.

## Conventions

- Frontmatter per the agentskills.io spec: `name` matches the directory,
  `description` includes an explicit "use when…" trigger.
- `SKILL.md` body stays under ~5000 tokens; detail lives in `references/`
  (one level deep, relative links only).
- Examples are Python (FastAPI, `x402` SDK, `stripe` SDK).
- Runnable demos live in each skill's `scripts/` directory; see each skill's
  `compatibility` field for dependencies.

## Example

[`examples/e2e-paid-api/`](examples/e2e-paid-api/README.md) wires all three
skills into one service: x402-paid endpoint + durable metering + a buyer that
runs the spend policy before signing. Offline tests included.

## Verify

```bash
pip install skills-ref==0.1.1
agentskills validate skills/<name>        # official spec validator
python scripts/validate_skills.py         # + links/token-budget checks
python -m compileall skills examples      # everything compiles
cd examples/e2e-paid-api && pytest tests -q   # offline end-to-end suite
```

CI runs all of the above on every push (Ubuntu + Windows). The skill demos in
`scripts/` self-test on launch; `agent-wallet-spend-policy` and
`ai-metering-billing` demos are pure stdlib.

## Roadmap: skills → tools (phase 2, not built yet)

Each skill's core operations are written as named, single-purpose steps so they
can later be exposed one-to-one as MCP tools:

| Future MCP tool | Source skill step |
| --- | --- |
| `quote_endpoint` / `handle_402` | `agentic-payments-protocols` — x402 402 flow |
| `verify_mandate` | `agentic-payments-protocols` — AP2 mandate verification |
| `report_usage` | `ai-metering-billing` — idempotent usage flush |
| `check_quota` | `ai-metering-billing` — quota/overage check |
| `check_spend_policy` | `agent-wallet-spend-policy` — pre-sign policy check |
| `post_entry` / `reconcile_breaks` | `payments-ledger-reconciliation` — journal + daily reconciliation |

For paid MCP tools, x402 defines an MCP transport: payment rides in
`_meta["x402/payment"]` with settlement results in
`_meta["x402/payment-response"]`
([spec](https://github.com/coinbase/x402/blob/main/specs/transports-v2/mcp.md)).
A future `server/` package can wrap these steps as MCP tools with that
transport; this pass ships skills and demos only.

## License

[MIT](LICENSE) — see also each skill's frontmatter.
