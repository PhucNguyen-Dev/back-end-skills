#!/usr/bin/env python
"""Pre-sign spend policy demo (stdlib only, runs offline).

All agent payments pass authorize() before a key would sign: schema check ->
allowlists -> velocity -> caps -> human threshold -> approve, with an
append-only hash-chained audit log written before signing.

    python demo_spend_policy.py    # runs self-tests on launch
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field


@dataclass(frozen=True)
class SpendPolicy:
    agent_id: str
    per_tx_limit_atomic: int
    daily_limit_atomic: int
    human_approval_threshold_atomic: int
    allowlisted_payees: frozenset[str]
    allowed_networks: frozenset[str] = frozenset({"eip155:8453"})
    allowed_assets: frozenset[str] = frozenset({"USDC"})
    max_attempts_per_minute: int = 20


@dataclass
class PaymentRequest:
    payee: str
    amount_atomic: int
    network: str = "eip155:8453"
    asset: str = "USDC"
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class Decision:
    outcome: str            # "approved" | "denied" | "pending_human"
    reasons: tuple[str, ...]


class AuditLog:
    """Append-only, hash-chained. Written before any signature."""

    def __init__(self) -> None:
        self._entries: list[dict] = []
        self._prev_hash = "0" * 64
        self._lock = threading.Lock()

    def append(self, record: dict) -> None:
        with self._lock:
            entry = {**record, "entry_id": uuid.uuid4().hex,
                     "ts": time.time(), "prev_hash": self._prev_hash}
            payload = json.dumps(entry, sort_keys=True).encode()
            entry["entry_hash"] = hashlib.sha256(payload).hexdigest()
            self._prev_hash = entry["entry_hash"]
            self._entries.append(entry)

    @property
    def entries(self) -> list[dict]:
        return list(self._entries)

    def verify_chain(self) -> bool:
        prev = "0" * 64
        for entry in self._entries:
            if entry["prev_hash"] != prev:
                return False
            body = {k: v for k, v in entry.items() if k != "entry_hash"}
            digest = hashlib.sha256(
                json.dumps(body, sort_keys=True).encode()).hexdigest()
            if digest != entry["entry_hash"]:
                return False
            prev = entry["entry_hash"]
        return True


class SpendTracker:
    """Per-agent spend + attempt velocity with atomic check-and-add."""

    def __init__(self) -> None:
        self._spent: dict[str, int] = {}
        self._attempts: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def too_fast(self, agent_id: str, limit_per_min: int) -> bool:
        now = time.time()
        with self._lock:
            hits = [t for t in self._attempts.get(agent_id, []) if now - t < 60]
            hits.append(now)
            self._attempts[agent_id] = hits
            return len(hits) > limit_per_min

    def would_exceed_daily(self, agent_id: str, amount: int, daily_limit: int) -> bool:
        with self._lock:
            return self._spent.get(agent_id, 0) + amount > daily_limit

    def commit(self, agent_id: str, amount: int) -> None:
        with self._lock:
            self._spent[agent_id] = self._spent.get(agent_id, 0) + amount


def authorize(request: PaymentRequest, policy: SpendPolicy,
              tracker: SpendTracker, audit: AuditLog) -> Decision:
    """Single choke point. Deny by default; log before any signing."""

    def finish(reasons: list[str], outcome: str) -> Decision:
        audit.append({"action": "payment.sign", "agent_id": policy.agent_id,
                      "request_id": request.request_id,
                      "amount_atomic": request.amount_atomic,
                      "payee": request.payee, "network": request.network,
                      "asset": request.asset, "decision": outcome,
                      "reasons": reasons, "policy_version": "v1"})
        return Decision(outcome, tuple(reasons))

    # 1. Schema / sanity: malformed never guesses its way to approval.
    if request.amount_atomic <= 0:
        return finish(["invalid_amount"], "denied")
    if not request.payee:
        return finish(["missing_payee"], "denied")

    # 2. Static allowlists.
    reasons: list[str] = []
    if request.payee not in policy.allowlisted_payees:
        reasons.append("payee_not_allowed")
    if request.network not in policy.allowed_networks:
        reasons.append("network_not_allowed")
    if request.asset not in policy.allowed_assets:
        reasons.append("asset_not_allowed")
    if reasons:
        return finish(reasons, "denied")

    # 3. Velocity.
    if tracker.too_fast(policy.agent_id, policy.max_attempts_per_minute):
        return finish(["velocity_exceeded"], "denied")

    # 4. Caps: hard denials — a human approval never rescues them.
    if request.amount_atomic > policy.per_tx_limit_atomic:
        return finish(["per_tx_limit"], "denied")
    if tracker.would_exceed_daily(policy.agent_id, request.amount_atomic,
                                  policy.daily_limit_atomic):
        return finish(["daily_limit"], "denied")

    # 5. Human approval threshold (within caps, but too big to auto-sign).
    if request.amount_atomic >= policy.human_approval_threshold_atomic:
        return finish(["requires_human_approval"], "pending_human")

    # 6. Approve (and only now is signing allowed).
    tracker.commit(policy.agent_id, request.amount_atomic)
    return finish(["ok"], "approved")


def self_test() -> int:
    audit = AuditLog()
    tracker = SpendTracker()
    policy = SpendPolicy(
        agent_id="agent_01",
        per_tx_limit_atomic=10_000_000,        # 10 USDC (6 decimals)
        daily_limit_atomic=25_000_000,         # 25 USDC
        human_approval_threshold_atomic=8_000_000,
        allowlisted_payees=frozenset({"0xGOOD", "merchant_42"}),
    )

    good = PaymentRequest(payee="0xGOOD", amount_atomic=1_000_000)
    assert authorize(good, policy, tracker, audit).outcome == "approved"

    # Unknown payee -> denied (allowlist, no exceptions).
    assert authorize(PaymentRequest(payee="0xEVIL", amount_atomic=1_000),
                     policy, tracker, audit).outcome == "denied"

    # Malformed amount -> denied, never "approved with warning".
    assert authorize(PaymentRequest(payee="0xGOOD", amount_atomic=0),
                     policy, tracker, audit).outcome == "denied"

    # Over per-tx cap -> denied.
    over_cap = authorize(PaymentRequest(payee="0xGOOD",
                                        amount_atomic=11_000_000),
                         policy, tracker, audit)
    assert over_cap.outcome == "denied" and "per_tx_limit" in over_cap.reasons

    # Above human threshold -> routes to a person, not auto-approved.
    pending = authorize(PaymentRequest(payee="0xGOOD",
                                       amount_atomic=8_500_000),
                        policy, tracker, audit)
    assert pending.outcome == "pending_human"
    assert "requires_human_approval" in pending.reasons

    # Daily budget: 3 x 7M approved = 21M spent of 25M; next 5M must be denied.
    for _ in range(3):
        assert authorize(PaymentRequest(payee="0xGOOD", amount_atomic=7_000_000),
                         policy, tracker, audit).outcome == "approved"
    daily = authorize(PaymentRequest(payee="0xGOOD", amount_atomic=5_000_000),
                      policy, tracker, audit)
    assert daily.outcome == "denied" and "daily_limit" in daily.reasons

    # Denials are logged, approvals are logged, chain verifies.
    decisions = [e["decision"] for e in audit.entries]
    assert "approved" in decisions and "denied" in decisions
    assert "pending_human" in decisions
    assert audit.verify_chain(), "audit hash chain broken"

    print("self-test OK")
    for entry in audit.entries:
        print(f"  {entry['decision']:<13} amount={entry['amount_atomic']:>9} "
              f"payee={entry['payee']:<12} reasons={','.join(entry['reasons'])}")
    print(f"audit chain verified: {len(audit.entries)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(self_test())
