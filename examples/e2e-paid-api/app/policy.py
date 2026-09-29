"""Pre-sign spend policy — checked before any key signs a payment.

Skill: agent-wallet-spend-policy — deny by default, integer atomic units,
allowlists first, hard caps that no approval rescues, human threshold above
which a person must confirm.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpendPolicy:
    per_tx_limit_atomic: int
    session_limit_atomic: int
    human_approval_threshold_atomic: int
    allowlisted_payees: frozenset[str]
    allowed_networks: frozenset[str] = frozenset({"eip155:84532"})
    allowed_assets: frozenset[str] = frozenset({"USDC"})


@dataclass(frozen=True)
class PaymentIntent:
    payee: str
    amount_atomic: int
    network: str
    asset: str = "USDC"
    description: str = ""


@dataclass(frozen=True)
class Decision:
    outcome: str  # "approved" | "denied" | "pending_human"
    reasons: tuple[str, ...] = ()

    @property
    def approved(self) -> bool:
        return self.outcome == "approved"


class SessionBudget:
    """In-memory session spend tracker with atomic check-and-add."""

    def __init__(self, limit_atomic: int) -> None:
        self.limit = limit_atomic
        self._spent = 0
        self._lock = threading.Lock()

    def would_exceed(self, amount: int) -> bool:
        with self._lock:
            return self._spent + amount > self.limit

    def commit(self, amount: int) -> None:
        with self._lock:
            self._spent += amount

    @property
    def spent(self) -> int:
        return self._spent


def authorize(intent: PaymentIntent, policy: SpendPolicy,
              budget: SessionBudget | None = None,
              human_confirmed: bool = False) -> Decision:
    """Single choke point. Deny by default; runs before any signing step."""
    if intent.amount_atomic <= 0:
        return Decision("denied", ("invalid_amount",))
    if not intent.payee:
        return Decision("denied", ("missing_payee",))

    reasons: list[str] = []
    if intent.payee not in policy.allowlisted_payees:
        reasons.append("payee_not_allowed")
    if intent.network not in policy.allowed_networks:
        reasons.append("network_not_allowed")
    if intent.asset not in policy.allowed_assets:
        reasons.append("asset_not_allowed")
    if reasons:
        return Decision("denied", tuple(reasons))

    if intent.amount_atomic > policy.per_tx_limit_atomic:
        return Decision("denied", ("per_tx_limit",))
    if budget is not None and budget.would_exceed(intent.amount_atomic):
        return Decision("denied", ("session_limit",))

    if intent.amount_atomic >= policy.human_approval_threshold_atomic:
        if human_confirmed:
            return Decision("approved", ("human_confirmed",))
        return Decision("pending_human", ("requires_human_approval",))

    return Decision("approved", ("ok",))
