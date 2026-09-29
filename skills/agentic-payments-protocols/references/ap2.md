# AP2 — proof that an agent is allowed to spend

Agent Payments Protocol (Google, donated to the FIDO Alliance). AP2
**authorizes**; it does not move money. Compose it with x402 (or cards/MPP)
for settlement. Python SDK: `google-agentic-commerce/AP2` (`code/sdk/python`).

## Core objects: mandates

A mandate is a cryptographically signed, tamper-evident record of user intent
(W3C Verifiable Credentials lineage; current SDK uses SD-JWT / KB-JWT chains).

| Mandate | Answers | Stage |
| --- | --- | --- |
| **Intent Mandate** | "What does the user want to buy?" | Human-present: agent drafts, user confirms |
| **Cart Mandate** | "Exactly what items/price did the merchant commit to?" | Merchant signs cart contents + price, short TTL |
| **Payment Mandate** | "May this transaction be charged to the instrument?" | Shared with network/issuer; agent involvement signalled |

v0.2 adds **Human Not Present** flows: pre-authorized instructions with
constraints (price ceilings, timing) for autonomous execution.

Mandates chain: every hop is signed and binds to the previous one
(`sd_hash` / `issuer_jwt_hash`), producing a non-repudiable audit trail.

## Python SDK: create → present → verify

```python
from ap2.sdk.mandate import MandateClient
from ap2.sdk.payment_mandate_chain import PaymentMandateChain
from ap2.sdk.utils import compute_sha256_b64url
from ap2.sdk.generated.open_payment_mandate import (
    AllowedPayees, AmountRange, OpenPaymentMandate,
)
from ap2.sdk.generated.payment_mandate import PaymentMandate
from ap2.sdk.generated.types.amount import Amount
from ap2.sdk.generated.types.merchant import Merchant
from ap2.sdk.generated.types.payment_instrument import PaymentInstrument

client = MandateClient()
now = 1_700_000_000

# 1. Issuer (user/credential provider) grants a scoped, open mandate.
open_token = client.create(
    payloads=[OpenPaymentMandate(
        constraints=[
            AmountRange(currency="USD", min=0, max=5000),
            AllowedPayees(allowed=[Merchant(id="M-1", name="Cat Store")]),
        ],
        cnf={"jwk": agent_pub},
        iat=now, exp=now + 3600,
    )],
    issuer_key=issuer_jwk,
)

# 2. Agent derives a closed mandate for one concrete transaction.
chain = client.present(
    holder_key=agent_jwk,
    mandate_token=open_token,
    payloads=[PaymentMandate(
        transaction_id="tx_abc",
        payee=Merchant(id="M-1", name="Cat Store"),
        payment_amount=Amount(amount=2500, currency="USD"),   # minor units
        payment_instrument=PaymentInstrument(type="card", id="stub", description="Demo"),
        iat=now, exp=now + 3600,
    )],
    nonce="tx_abc",
    aud="merchant",
)

# 3. Merchant verifies the whole chain and the constraints.
payloads = client.verify(
    token=chain,
    key_or_provider=lambda token: issuer_jwk,   # root issuer key only
    expected_aud="merchant",
    expected_nonce="tx_abc",
)
parsed = PaymentMandateChain.parse(payloads)
violations = parsed.verify(expected_transaction_id="tx_abc")
assert not violations

# 4. Receipt binds to the closed leaf JWT (stable across depth/disclosures).
reference = compute_sha256_b64url(client.get_closed_mandate_jwt(chain))
```

Flow roles: **Credential Provider** (holds payment methods), **Merchant**,
**Merchant Payment Processor**, **Network/Issuer**. The agent only ever holds
delegated, constrained authority — never the instrument itself.

## Verification rules

- Trust anchors at the **root issuer key** only; each hop validates via the
  preceding hop's `cnf.jwk`.
- `aud` + `nonce` are required on KB-SD-JWT presentations — without them the
  binding to *this* transaction is unproven.
- Constraint checks (`AmountRange`, `AllowedPayees`, per-SKU rules) are your
  spend policy expressed declaratively — mirror them in code before signing
  (see `agent-wallet-spend-policy` skill).
- Short TTLs everywhere: intents hours, carts minutes (5–15).

## When to use AP2

- Enterprise/audit: "prove the human authorized this" holds up in dispute
  resolution.
- Human-not-present purchases within pre-AP2-approved limits.
- Anything where issuer/network wants an explicit agent-involvement signal.

Do **not** use AP2 alone to move money, and don't wait on it for simple
API micropayments — x402 covers that today. AP2 + x402 is a supported
composition (A2A x402 extension).
