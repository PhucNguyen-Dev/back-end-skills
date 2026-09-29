# Protocol selection — decision matrix

## By task

| Task | Primary | Compose with | Why |
| --- | --- | --- | --- |
| Monetize an API (per call, sub-dollar) | x402 `exact` | metering (`ai-metering-billing`) | Stateless, no accounts, card economics don't work at $0.003/call |
| Monetize variable-cost AI work (tokens) | x402 `upto` | metering | Authorize max, settle actual after the model runs |
| High-frequency agent session (1000s of calls) | MPP session, or x402 `batch-settlement` | spend policy | Per-request settlement is too expensive/noisy |
| Agent buys from a store | ACP | AP2 mandates | Merchant integration + authority |
| Enterprise purchase needing audit proof | AP2 | x402 or cards | Cryptographic proof of user intent |
| Agent pays for compute/data with no prior relationship | x402 | spend policy | Self-describing 402, instant onboarding |
| Fiat-only merchant, human-visible purchase | ACP/Stripe | AP2 signal | Installed base of Visa-accepting merchants |

## By counterparty and scale

- **No pre-existing relationship** → x402 (permissionless; the 402 response
  *is* the onboarding).
- **Contracted merchant, conventional cart values** → ACP; MPP if you want
  crypto+fiat settlement under one session cap.
- **Regulated enterprise ("who authorized this?")** → AP2 mandates regardless
  of settlement rail.
- **Compliance-heavy deployment**: stablecoin rails are final (no chargeback)
  and regulated (GENIUS Act in US, MiCA in EU) — pair them with preventive
  policy, not dispute workflows.

## Stacking them

```
   Authority:   AP2 (mandates prove user intent)
   Commerce:    ACP (agent ↔ merchant checkout)
   Settlement:  x402 (per-request)  |  MPP (sessions)  |  cards
   Controls:    spend policy enforced in code, outside the model
                (agent-wallet-spend-policy skill)
   Revenue:     metering + billing pipeline
                (ai-metering-billing skill)
```

Convergence is real: Stripe supports MPP and x402; AP2 ships an x402
extension; ACP tokens ride MPP sessions. Build the layers you need, keep
settlement behind one interface so rails can change.

## Maturity notes (2026)

| Protocol | Status |
| --- | --- |
| x402 | Production; live volume; v2 (sessions, discovery, CAIP); Foundation operational |
| MPP | Live on Tempo; Stripe PaymentIntents acceptance |
| ACP | Live at Stripe-enabled merchants |
| AP2 | v0.2 pre-release; FIDO working groups; implementations emerging |

Bias toward x402 + metering + spend policy for API/backend work today; adopt
AP2 when audit requirements demand it; watch MPP for session-heavy agents.
