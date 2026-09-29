# back-end-skills

A suite of [Agent Skills](https://agentskills.io/specification) for building
**AI payment infrastructure** on the backend. Each skill teaches an agent one
route through the money stack:

| Skill | Route | Direction |
| --- | --- | --- |
| [`agentic-payments-protocols`](skills/agentic-payments-protocols/SKILL.md) | Charge for HTTP resources, pay for services as an agent | Sell to agents (x402), buy with proof of authority (AP2) |
| [`ai-metering-billing`](skills/ai-metering-billing/SKILL.md) | Meter AI usage → bill → collect | Turn token/invocation usage into revenue |
| [`agent-wallet-spend-policy`](skills/agent-wallet-spend-policy/SKILL.md) | Keys, spend caps, allowlists, audit | Let agents spend — only within policy enforced in code |

Together: one path makes your API earn from agents, one makes your agent spend
safely, and metering ties both to billing.

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

## Verify

```bash
python scripts/validate_skills.py          # spec checks (or: py -3 on Windows)
python -m compileall skills                # every demo compiles
```

`agent-wallet-spend-policy/scripts/demo_spend_policy.py` runs offline with the
standard library and self-tests on launch.

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

For paid MCP tools, x402 defines an MCP transport: payment rides in
`_meta["x402/payment"]` with settlement results in
`_meta["x402/payment-response"]`
([spec](https://github.com/coinbase/x402/blob/main/specs/transports-v2/mcp.md)).
A future `server/` package can wrap these steps as MCP tools with that
transport; this pass ships skills and demos only.

## License

MIT (see each skill's frontmatter).
