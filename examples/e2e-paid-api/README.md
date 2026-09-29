# e2e-paid-api — one backend, all four skills

A small FastAPI service that charges per request (x402), meters what was
consumed (durable, idempotent), posts every settlement to a balanced
append-only ledger, and a buyer agent that runs a spend policy **before any
key signs**.

| Piece | Skill applied |
| --- | --- |
| `app/server.py` — `PaymentMiddlewareASGI` on `GET /paid/report` | `agentic-payments-protocols` |
| `app/server.py` — meter record keyed to the payment's EIP-3009 nonce | `ai-metering-billing` |
| `app/meter.py` — unique-key SQLite ingestion, `increment` flush plan | `ai-metering-billing` |
| `app/buyer.py` — `authorize()` runs between 402 and signing | `agent-wallet-spend-policy` |
| `app/policy.py` — allowlist / caps / human threshold, deny by default | `agent-wallet-spend-policy` |
| `app/ledger.py` — balanced cash/revenue entries, trial balance = 0 | `payments-ledger-reconciliation` |
| `app/webhooks.py` — raw-body signature verify + idempotent event dispatch | `ai-metering-billing` |
| `app/signing.py` — DevKeySigner (env, dev only) / KmsSigner seam | `agent-wallet-spend-policy` |

## Run

```bash
pip install -r requirements.txt          # or uv pip install -r requirements.txt
```

**Offline tests** (no network, no keys):

```bash
pytest tests -q
```

**Interactive demo** (two terminals):

```bash
python -m app.server           # terminal 1: serves on :8402
python -m app.buyer --dry-run  # terminal 2: 402 -> quote -> policy -> stops
```

The buyer prints the quote (`1000 atomic units -> 0x…dEaD`), the policy
decision, and stops before signing. Exit codes: `0` approved, `2` denied,
`3` pending human confirmation.

**Deny path** (show the allowlist bite):

```bash
set ALLOWED_PAYEES=0x1111111111111111111111111111111111111111
python -m app.buyer            # -> denied (payee_not_allowed), no signature
```

**Real testnet payment** (Base Sepolia):

```bash
# terminal 1: set your receiving address
set EVM_ADDRESS=0xYourSepoliaAddress
python -m app.server

# terminal 2: funded testnet wallet + allowlist matching the server
set ALLOWED_PAYEES=0xYourSepoliaAddress
set WALLET_PRIVATE_KEY=0xYourFundedKey
python -m app.buyer --yes
```

`--yes` simulates human confirmation (policy threshold is 0.5 USDC; the
$0.001 default price doesn't need it — it matters for larger quotes).
Get testnet USDC from a Base Sepolia faucet; the default facilitator is
`https://x402.org/facilitator`.

**Usage endpoints**:

```bash
curl http://127.0.0.1:8402/usage            # metered totals this period
curl http://127.0.0.1:8402/flush            # Stripe-shaped increment plan
curl http://127.0.0.1:8402/balance          # ledger accounts, trial balance 0
```

Set `STRIPE_API_KEY` + `STRIPE_SUBSCRIPTION_ITEM_ID` to actually POST the
flush to Stripe.

**Stripe webhooks** (`POST /webhooks/stripe`):

```bash
set STRIPE_WEBHOOK_SECRET=whsec_...
stripe listen --forward-to localhost:8402/webhooks/stripe
```

The endpoint verifies the `stripe-signature` header against the **raw body**
(300s tolerance), journaling `event.id` so retries/replays dispatch handlers
exactly once, returns `200` fast for handled *and* unhandled events, and
fails closed (`503`) when no secret is configured. Ship-state handlers for
`invoice.paid` / `invoice.payment_failed` live in `app/webhooks.py`.

## Environment

| Var | Default | Used by |
| --- | --- | --- |
| `EVM_ADDRESS` | `0x…dEaD` | server — receive address |
| `X402_PRICE` | `$0.001` | server — per-request price |
| `X402_NETWORK` | `eip155:84532` (Base Sepolia) | server |
| `FACILITATOR_URL` | `https://x402.org/facilitator` | server |
| `ALLOWED_PAYEES` | `0x…dEaD` (comma-separated) | buyer — policy allowlist |
| `WALLET_PRIVATE_KEY` | — | buyer — only for real payment |
| `STRIPE_API_KEY` / `STRIPE_SUBSCRIPTION_ITEM_ID` | — | server — optional live flush |
| `STRIPE_WEBHOOK_SECRET` | — | server — webhook verify; unset = 503 (fail closed) |

## Design notes

- **Meter once per payment**: the idempotency key is the EIP-3009
  authorization nonce — unique per signed payment, so a retried request can
  never double-count.
- **Policy before signature**: `authorize()` sees only the 402's
  requirements (amount, payee, network). Deny means no key was ever touched.
- **Swappable custody**: `pay()` takes any signer with `.address` +
  `.sign_typed_data(...)` — `DevKeySigner` (env key, dev/testnet) today;
  production swaps in `KmsSigner` without touching policy or flow.
- **Identity for metering** comes from the verified `PAYMENT-SIGNATURE`
  header the middleware already validated; requests without one meter as
  `anonymous` (the middleware never lets them reach the paid handler).
- **Increment-only flushing**: usage records are reported with
  `action="increment"`, so a retried batch can't under-bill.
- **Ledger mirrors settlement**: each paid request posts one balanced entry
  (cash `1000` / revenue `4000`, USDC atomic units) keyed by the same nonce —
  replays are idempotent and `GET /balance`'s trial balance always sums to
  zero. Unbalanced entries are rejected at write time.
