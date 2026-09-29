#!/usr/bin/env python3
"""Ledger + reconciliation demo — Python stdlib only, self-tests on launch.

Simulates a day of money movement, then runs a three-way reconciliation
(journal vs settlement receipts vs external statements) and reports breaks.
"""
from __future__ import annotations


class UnbalancedEntry(Exception):
    pass


class Ledger:
    """Append-only double-entry journal, idempotent by entry_id."""

    def __init__(self) -> None:
        self._entries: dict[str, list[tuple[str, int]]] = {}

    def post(self, entry_id: str, postings: list[tuple[str, int]]) -> bool:
        """Post one balanced entry. Returns False on replay (idempotent)."""
        if entry_id in self._entries:
            return False
        if not postings:
            raise ValueError("entry needs at least one posting")
        if sum(amount for _, amount in postings) != 0:
            raise UnbalancedEntry(f"{entry_id}: postings do not balance")
        self._entries[entry_id] = list(postings)
        return True

    def balances(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for postings in self._entries.values():
            for account, amount in postings:
                totals[account] = totals.get(account, 0) + amount
        return dict(sorted(totals.items()))

    def cash_legs(self) -> dict[str, int]:
        """Net cash posting per receipt id (positive = cash in)."""
        out: dict[str, int] = {}
        for entry_id, postings in self._entries.items():
            if entry_id.startswith("settle_"):
                out_entry = sum(amt for acct, amt in postings if acct == "1000")
                out[entry_id.removeprefix("settle_")] = out_entry
        return out

    @property
    def trial_balance(self) -> int:
        return sum(self.balances().values())


def settle(ledger: Ledger, rid: str, receipt: dict) -> bool:
    """One settlement = one entry: cash net, fee, revenue (integer cents)."""
    return ledger.post(
        f"settle_{rid}",
        [
            ("1000", receipt["gross"] - receipt["fee"]),   # cash up
            ("5000", receipt["fee"]),                      # fee expense
            ("4000", -receipt["gross"]),                   # revenue
        ],
    )


def reconcile(
    ledger: Ledger,
    receipts: dict[str, dict],
    statements: dict[str, int],
) -> list[dict]:
    """Three-way match: journal <-> operational receipts <-> external statement."""
    breaks: list[dict] = []
    cash = ledger.cash_legs()
    for rid in sorted(set(receipts) | set(statements) | set(cash)):
        in_ledger, in_receipts, in_stmt = rid in cash, rid in receipts, rid in statements
        if not in_ledger and (in_receipts or in_stmt):
            breaks.append({"id": rid, "type": "missing-in-ledger"})
            continue
        if in_ledger and not in_receipts:
            breaks.append({"id": rid, "type": "missing-in-receipts"})
        if in_ledger and not in_stmt:
            breaks.append({"id": rid, "type": "missing-in-statement"})
        if in_ledger and in_stmt and cash[rid] != statements[rid]:
            breaks.append({"id": rid, "type": "amount-mismatch",
                           "ledger": cash[rid], "statement": statements[rid]})
        if in_ledger and in_receipts:
            net = receipts[rid]["gross"] - receipts[rid]["fee"]
            if cash[rid] != net:
                breaks.append({"id": rid, "type": "amount-mismatch",
                               "ledger": cash[rid], "receipt_net": net})
    return breaks


def _self_test() -> None:
    ledger = Ledger()

    # 1. balanced entries post; trial balance stays zero
    receipts = {
        "001": {"gross": 1000, "fee": 30},
        "002": {"gross": 2500, "fee": 50},
        "003": {"gross": 750, "fee": 20},
    }
    settle(ledger, "001", receipts["001"])
    settle(ledger, "002", receipts["002"])
    # receipt 003 intentionally dropped: planted "listener lost an event" break
    assert ledger.trial_balance == 0

    # 2. unbalanced entry is rejected
    try:
        ledger.post("bad", [("1000", 100), ("4000", -99)])
        raise AssertionError("unbalanced entry was accepted")
    except UnbalancedEntry:
        pass

    # 3. replayed webhook posts exactly once
    before = len(ledger._entries)
    settle(ledger, "001", receipts["001"])   # duplicate event replay
    assert len(ledger._entries) == before

    # 4. refunds are append-only contra entries (history intact)
    ledger.post("refund_001", [("4100", 100), ("1000", -100)])
    assert ledger.trial_balance == 0
    assert len(ledger._entries) == 3

    # 5. three-way reconciliation finds exactly the planted breaks
    statements = {"001": 970, "002": 2400, "003": 730}  # 002 chain fee differs
    breaks = reconcile(ledger, receipts, statements)
    found = {(b["id"], b["type"]) for b in breaks}
    assert found == {
        ("002", "amount-mismatch"),
        ("003", "missing-in-ledger"),
    }, found

    # 6. after fixing the listener gap, only the amount break remains
    settle(ledger, "003", receipts["003"])
    breaks = reconcile(ledger, receipts, statements)
    assert {b["type"] for b in breaks} == {"amount-mismatch"}
    assert ledger.trial_balance == 0


def main() -> None:
    _self_test()

    ledger = Ledger()
    receipts = {
        "001": {"gross": 1000, "fee": 30},
        "002": {"gross": 2500, "fee": 50},
        "003": {"gross": 750, "fee": 20},
    }
    for rid, r in receipts.items():
        settle(ledger, rid, r)
    ledger.post("refund_001", [("4100", 100), ("1000", -100)])

    print("balances (minor units):", ledger.balances())
    print("trial balance:", ledger.trial_balance)

    statements = {"001": 970, "002": 2400, "003": 730}
    breaks = reconcile(ledger, receipts, statements)
    print(f"reconciliation: {3 - len(breaks)}/3 matched, {len(breaks)} break(s)")
    for b in breaks:
        print(f"  BREAK {b['type']:<22} id={b['id']} {b}")
    print("self-test OK")


if __name__ == "__main__":
    main()
