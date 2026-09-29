"""Signer abstraction tests: DevKey env path + KMS shape.

    pytest tests/test_signing.py -q
"""

from __future__ import annotations

import hashlib

from app.signing import DevKeySigner, KmsSigner, signer_from_env

KEY = "0x" + "ab" * 32

DOMAIN = {"name": "test", "version": "1", "chainId": 84532,
          "verifyingContract": "0x" + "11" * 20}
TYPES = {"Mail": [{"name": "contents", "type": "string"}]}
MESSAGE = {"contents": "hello"}


def test_dev_signer_address_and_signature_shape():
    from eth_account import Account

    signer = DevKeySigner(KEY)
    assert signer.address == Account.from_key(KEY).address

    signature = signer.sign_typed_data(DOMAIN, TYPES, "Mail", MESSAGE)
    assert len(signature) == 65
    assert signature[-1] in (27, 28)
    # EIP-712 signing is deterministic: same data -> same signature
    assert signature == signer.sign_typed_data(DOMAIN, TYPES, "Mail", MESSAGE)


def test_signer_from_env(monkeypatch):
    monkeypatch.setenv("WALLET_PRIVATE_KEY", KEY)
    signer = signer_from_env()
    assert isinstance(signer, DevKeySigner)
    assert signer.address.startswith("0x")


def test_dev_signer_requires_key(monkeypatch):
    monkeypatch.delenv("WALLET_PRIVATE_KEY", raising=False)
    try:
        DevKeySigner()
        raise AssertionError("missing key should exit")
    except SystemExit:
        pass


def test_kms_signer_shape_refuses_to_sign():
    signer = KmsSigner("0x" + "22" * 20, key_id="projects/p/locations/l/key/k")
    assert signer.address == "0x" + "22" * 20
    try:
        signer.sign_typed_data(DOMAIN, TYPES, "Mail", MESSAGE)
        raise AssertionError("stub must never sign")
    except NotImplementedError as exc:
        assert "KMS" in str(exc)


def test_custody_seam_is_sign_typed_data():
    # The custody seam is sign_typed_data (what ExactEvmClientScheme calls).
    # A raw sign_digest() would invite key-material flows we do not implement.
    assert hasattr(DevKeySigner(KEY), "sign_typed_data")
    assert not hasattr(DevKeySigner(KEY), "sign_digest")
