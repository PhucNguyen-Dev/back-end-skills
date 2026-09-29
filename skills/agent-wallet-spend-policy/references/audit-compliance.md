# Audit & compliance — evidence that survives scrutiny

## Append-only audit log

One row per decision, written **before** the signature:

```json
{
  "entry_id": "0193f2c1-…",
  "ts": "2026-09-29T12:00:00.123Z",
  "agent_id": "agent_procurement_01",
  "session_id": "sess_abc",
  "action": "payment.sign",
  "request": {"amount_atomic": "2500", "asset": "USDC",
              "network": "eip155:8453", "payee": "0x…"},
  "decision": "approved" | "denied" | "pending_human",
  "reasons": ["ok"],
  "policy_version": "v7",
  "authority_ref": "mandate_sha256:… or budget:sess_abc",
  "approver": null,
  "tx_hash": null,
  "prev_hash": "…",
  "entry_hash": "…"
}
```

- **Hash chain** (`entry_hash = H(prev_hash || entry)`) makes tampering
  detectable; sign batches with an external key for stronger guarantees.
- Immutable storage: append-only table/WORM bucket; corrections are new rows,
  never updates.
- Exportable: someone with subpoena power must be able to reconstruct "what
  was this agent authorized to do *at the moment it acted*".

## What to record

| Phase | Events |
| --- | --- |
| Authority | mandate issued/verified, budget granted, session key issued |
| Decision | every authorize() result — approvals *and* denials |
| Money | payment signed, settlement receipt/tx hash, invoice/usage flush |
| Access | key rotation/revocation, policy version changes |

## Reconciliation

- Daily: `sum(signed payments)` vs `sum(settlement receipts)` vs
  `sum(metered usage)` — investigate every gap.
- Alert on: denied-check spikes, approval requests above baseline, velocity
  anomalies, failed replay/nonce checks.

## Regulatory context (2026)

Agents settle on rails that are already regulated:

| Regime | Covers |
| --- | --- |
| **GENIUS Act** (US, 2025) | payment stablecoins: reserves, disclosure, supervisory perimeter for issuers |
| **MiCA** (EU) | crypto-asset services + stablecoin issuance; Travel Rule data obligations on transfers |
| **EU AI Act** (phasing in) | transparency/human oversight obligations for AI systems in scope |
| **DORA** (EU finance) | operational resilience — reaches your vendors |

Implications for builders: keep originator/beneficiary data for transfers
where required, know your counterparty (allowlists help here too), retain
audit trails per record-keeping rules, and treat human-approval thresholds as
the "human oversight" control your compliance team will ask about.

## Dispute posture

- On stablecoin rails there is **no chargeback** — your only remedies are
  prevention (policy) and cooperation/courts after the fact.
- On card rails disputes exist — keep receipts, mandates, and delivery
  evidence linked to `entry_id` so responses are mechanical.
- Either way: evidence gathered at decision time is the whole game.
