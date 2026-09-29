"""Live settlement integration test (Base Sepolia) — opt-in.

Runs only when X402_LIVE_TEST=1 and WALLET_PRIVATE_KEY is funded with testnet
USDC (+ gas): real facilitator verify/settle, real chain transfer, real server
process over TCP. Skipped everywhere else (including CI).

    set X402_LIVE_TEST=1
    set WALLET_PRIVATE_KEY=0x...        # Base Sepolia USDC + ETH
    pytest tests/test_settlement_live.py -v
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time

import httpx
import pytest
from x402.http import PAYMENT_REQUIRED_HEADER, decode_payment_required_header

pytestmark = pytest.mark.skipif(
    os.getenv("X402_LIVE_TEST") != "1" or not os.getenv("WALLET_PRIVATE_KEY"),
    reason="live settlement: set X402_LIVE_TEST=1 + funded WALLET_PRIVATE_KEY",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int) -> subprocess.Popen:
    example_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = dict(os.environ, PORT=str(port))
    return subprocess.Popen(
        [sys.executable, "-m", "app.server"],
        cwd=example_root, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )


def test_full_settlement_roundtrip():
    from eth_account import Account

    from app.buyer import pay
    from app.server import PRICE_ATOMIC

    payer = Account.from_key(os.environ["WALLET_PRIVATE_KEY"])
    port = _free_port()
    server = _start_server(port)
    base = f"http://127.0.0.1:{port}"

    try:
        deadline = time.time() + 30
        while True:
            try:
                unpaid = httpx.get(f"{base}/paid/report", timeout=2)
                break
            except httpx.HTTPError:
                if server.poll() is not None:
                    out = server.stdout.read().decode(errors="replace")
                    raise RuntimeError(f"server died during startup:\n{out}")
                if time.time() > deadline:
                    raise RuntimeError("server did not start within 30s")
                time.sleep(0.5)
        assert unpaid.status_code == 402, unpaid.text

        payment_required = decode_payment_required_header(
            unpaid.headers[PAYMENT_REQUIRED_HEADER])
        paid = pay(f"{base}/paid/report", payment_required)
        assert paid.status_code == 200, paid.text
        assert paid.headers.get("payment-response"), "missing settlement receipt"
        body = paid.json()
        assert body["metered"] is True
        assert body["charged_atomic"] == str(PRICE_ATOMIC)

        usage = httpx.get(f"{base}/usage", timeout=5).json()
        assert any(
            row["customer_id"].lower() == payer.address.lower()
            and row["quantity"] >= 1
            for row in usage["totals"]
        ), usage

        balance = httpx.get(f"{base}/balance", timeout=5).json()
        assert balance["trial_balance"] == 0
        assert balance["balances"]["1000"] == PRICE_ATOMIC
        assert balance["balances"]["4000"] == -PRICE_ATOMIC
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
