import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

from mensarium.shared.paths import write_private


def canonical_json(data: Any) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256_hex(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def load_or_create_private_key(path: Path) -> Ed25519PrivateKey:
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        assert isinstance(key, Ed25519PrivateKey)
        return key
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    write_private(path, pem)
    return key


def public_key_b64(key: Ed25519PrivateKey) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def load_public_key(b64: str) -> Ed25519PublicKey:
    return Ed25519PublicKey.from_public_bytes(base64.b64decode(b64))


def fingerprint(public_b64: str) -> str:
    digest = hashlib.sha256(base64.b64decode(public_b64)).hexdigest()[:16].upper()
    return ":".join(digest[i : i + 4] for i in range(0, 16, 4))


def sign(key: Ed25519PrivateKey, payload: dict[str, Any]) -> str:
    body = {k: v for k, v in payload.items() if k != "signature"}
    return "ed25519:" + base64.b64encode(key.sign(canonical_json(body))).decode()


def verify(public_b64: str, payload: dict[str, Any]) -> bool:
    signature = payload.get("signature") or ""
    if not signature.startswith("ed25519:"):
        return False
    body = {k: v for k, v in payload.items() if k != "signature"}
    try:
        load_public_key(public_b64).verify(base64.b64decode(signature[8:]), canonical_json(body))
    except (InvalidSignature, ValueError):
        return False
    return True
