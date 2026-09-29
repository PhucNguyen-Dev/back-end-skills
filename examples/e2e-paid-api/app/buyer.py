"""Buyer agent: fetch -> 402 -> PRE-SIGN policy check -> pay only if approved.

Skills: agent-wallet-spend-policy (authorize() runs before any key signs),
agentic-payments-protocols (x402 402 -> PAYMENT-SIGNATURE -> retry).

    python -m app.buyer                 # unpaid attempt + policy decision
    python -m app.buyer --dry-run       # stop after an approved decision
    python -m app.buyer --yes           # confirm a human-approved payment
    WALLET_PRIVATE_KEY=0x... python -m app.buyer --yes   # real testnet payment
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx
from x402 import x402ClientSync
from x402.http import (
    PAYMENT_REQUIRED_HEADER,
    PAYMENT_SIGNATURE_HEADER,
    decode_payment_required_header,
    x402HTTPClientSync,
)
from x402.mechanisms.evm.exact import ExactEvmClientScheme
from x402.mechanisms.evm.signers import EthAccountSigner

from app.policy import Decision, PaymentIntent, SpendPolicy, SessionBudget, authorize

DEFAULT_URL = "http://127.0.0.1:8402/paid/report"

# USDC contract addresses recognized as the settlement asset.
USDC_ADDRESSES = frozenset({
    "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia
    "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # Base mainnet
})

DEFAULT_PAYEE = "0x000000000000000000000000000000000000dEaD"


def default_policy() -> SpendPolicy:
    payees = os.getenv("ALLOWED_PAYEES", DEFAULT_PAYEE)
    return SpendPolicy(
        per_tx_limit_atomic=1_000_000,             # 1 USDC per payment
        session_limit_atomic=5_000_000,            # 5 USDC per session
        human_approval_threshold_atomic=500_000,   # >= 0.5 USDC needs a human
        allowlisted_payees=frozenset(p.strip() for p in payees.split(",") if p.strip()),
    )


def intent_from_requirements(requirements: object) -> PaymentIntent:
    """Map a 402 PaymentRequirements to a policy-checkable intent."""
    pay_to = str(getattr(requirements, "pay_to", "") or "")
    amount = int(getattr(requirements, "amount", 0) or 0)
    network = str(getattr(requirements, "network", "") or "")
    extra = getattr(requirements, "extra", None) or {}
    asset = str(extra.get("name", getattr(requirements, "asset", ""))) \
        if isinstance(extra, dict) else str(getattr(requirements, "asset", ""))
    if asset in USDC_ADDRESSES:
        asset = "USDC"
    return PaymentIntent(payee=pay_to, amount_atomic=amount,
                         network=network, asset=asset,
                         description="GET /paid/report")


def pay(url: str, payment_required: object) -> httpx.Response:
    """Sign and retry. Only ever called after authorize() approved."""
    private_key = os.environ.get("WALLET_PRIVATE_KEY")
    if not private_key:
        raise SystemExit("approved, but WALLET_PRIVATE_KEY is not set "
                         "(set a funded Base Sepolia testnet key to pay)")

    from eth_account import Account

    account = Account.from_key(private_key)
    client = x402ClientSync()
    client.register("eip155:*",
                    ExactEvmClientScheme(EthAccountSigner(account)))
    http_client = x402HTTPClientSync(client)
    payload = http_client.create_payment_payload(payment_required)
    encoded = http_client.encode_payment_signature_header(payload)
    headers = (encoded if isinstance(encoded, dict)
               else {PAYMENT_SIGNATURE_HEADER: encoded})
    with httpx.Client() as hx:
        response = hx.get(url, headers=headers)
    return response


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--dry-run", action="store_true",
                        help="stop after an approved decision; never sign")
    parser.add_argument("--yes", action="store_true",
                        help="simulate human confirmation for large payments")
    args = parser.parse_args(argv)

    with httpx.Client(timeout=10) as hx:
        response = hx.get(args.url)

    if response.status_code != 402:
        print(f"expected 402, got {response.status_code}: "
              f"{response.text[:200]}")
        return 1

    header = response.headers.get(PAYMENT_REQUIRED_HEADER)
    if not header:
        print("402 without a payment-required header")
        return 1
    payment_required = decode_payment_required_header(header)
    requirement = payment_required.accepts[0]
    intent = intent_from_requirements(requirement)

    policy = default_policy()
    budget = SessionBudget(policy.session_limit_atomic)
    decision: Decision = authorize(intent, policy, budget,
                                   human_confirmed=args.yes)

    print(f"quote: {intent.amount_atomic} atomic units "
          f"({intent.amount_atomic / 1_000_000:.6f} USDC) "
          f"-> {intent.payee} on {intent.network}")
    print(f"policy: {decision.outcome} ({', '.join(decision.reasons)})")

    if decision.outcome == "denied":
        print("no signature was created (deny by default)")
        return 2
    if decision.outcome == "pending_human":
        print("a human must confirm: re-run with --yes")
        return 3
    if args.dry_run:
        print("approved; --dry-run set, not signing")
        return 0

    result = pay(args.url, payment_required)
    if result.status_code == 200:
        budget.commit(intent.amount_atomic)
        print(f"paid + metered: {result.text[:300]}")
        print(f"receipt header: {result.headers.get('payment-response', '(none)')[:160]}")
        return 0
    print(f"payment retry failed: {result.status_code} {result.text[:300]}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
