"""Signing abstraction: dev key now, KMS/HSM/MPC later.

Skill: agent-wallet-spend-policy — custody boundary. Everything upstream
(policy, quote, allowlist) is signer-agnostic: swapping the implementation
changes where the key lives, never what gets approved.

The interface is exactly what `ExactEvmClientScheme` consumes:
`.address` + `.sign_typed_data(domain, types, primary_type, message)`.

    DevKeySigner   private key from env — DEVELOPMENT / TESTNET ONLY
    KmsSigner      remote-signing shape for production (KMS/HSM/MPC)
"""

from __future__ import annotations

import os
from typing import Any, Protocol

from x402.mechanisms.evm.signers import EthAccountSigner


class Signer(Protocol):
    @property
    def address(self) -> str: ...

    def sign_typed_data(self, domain: Any, types: dict, primary_type: str,
                        message: dict) -> bytes: ...


class DevKeySigner:
    """Wraps an env-held key via the x402 SDK's EthAccountSigner.

    Never use beyond local/testnet: the key sits in process env/memory, so
    any code execution risk becomes key theft risk.
    """

    def __init__(self, private_key: str | None = None) -> None:
        from eth_account import Account

        key = private_key or os.environ.get("WALLET_PRIVATE_KEY")
        if not key:
            raise SystemExit(
                "approved, but WALLET_PRIVATE_KEY is not set "
                "(set a funded Base Sepolia testnet key to pay)")
        self._impl = EthAccountSigner(Account.from_key(key))

    @property
    def address(self) -> str:
        return self._impl.address

    def sign_typed_data(self, domain: Any, types: dict, primary_type: str,
                        message: dict) -> bytes:
        return self._impl.sign_typed_data(domain, types, primary_type, message)


class KmsSigner:
    """Production shape: key material never enters this process.

    Wire your cloud KMS / HSM / MPC client into `sign_typed_data`:
    compute the EIP-712 digest locally from (domain, types, message), send
    the digest to the remote signer, return the 65-byte signature. Provide
    `address` from the key's public key (derived once at registration).

    Intentionally not implemented here — no cloud SDK dependency, and a
    stub that silently signs with anything would be a footgun.
    """

    def __init__(self, address: str, key_id: str) -> None:
        self._address = address
        self.key_id = key_id

    @property
    def address(self) -> str:
        return self._address

    def sign_typed_data(self, domain: Any, types: dict, primary_type: str,
                        message: dict) -> bytes:
        raise NotImplementedError(
            f"KmsSigner({self.key_id}): route the EIP-712 digest to your "
            "KMS/HSM client here — production signing must never come from "
            "an environment key (see DevKeySigner).")


def signer_from_env() -> DevKeySigner:
    """Dev/testnet signer from WALLET_PRIVATE_KEY."""
    return DevKeySigner()
