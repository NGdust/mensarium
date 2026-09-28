import io
import json
import os
import shutil
import sqlite3
import tarfile
import tempfile
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from mensarium import __version__
from mensarium.core.config import CorePaths
from mensarium.shared.crypto import sha256_hex
from mensarium.shared.timeutil import now_iso

MAGIC = b"PAB1"


class BackupError(Exception):
    pass


def _key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())


def export_bundle(paths: CorePaths, out: Path, passphrase: str) -> dict[str, object]:
    if not paths.config.exists():
        raise BackupError("core is not configured on this host")
    with tempfile.TemporaryDirectory() as tmp:
        db_copy = Path(tmp) / "mensarium.db"
        if paths.db.exists():
            src, dst = sqlite3.connect(paths.db), sqlite3.connect(db_copy)
            with dst:
                src.backup(dst)
            src.close()
            dst.close()
        artifacts = list(paths.artifacts.glob("*")) if paths.artifacts.exists() else []
        manifest = {
            "format_version": 1,
            "core_version": __version__,
            "created_at": now_iso(),
            "artifact_count": len(artifacts),
            "encryption": {"algorithm": "scrypt+aes-256-gcm"},
        }
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tar:
            data = json.dumps(manifest, indent=2).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
            if db_copy.exists():
                tar.add(db_copy, arcname="mensarium.db")
            for name in ("config.yaml", "secrets", "keys", "artifacts", "skills", "instructions"):
                if (paths.root / name).exists():
                    tar.add(paths.root / name, arcname=name)
    plain = buf.getvalue()
    salt, nonce = os.urandom(16), os.urandom(12)
    blob = MAGIC + salt + nonce + AESGCM(_key(passphrase, salt)).encrypt(nonce, plain, MAGIC)
    out.write_bytes(blob)
    out.chmod(0o600)
    return {**manifest, "file": str(out), "sha256": sha256_hex(blob), "size": len(blob)}


def import_bundle(paths: CorePaths, bundle: Path, passphrase: str) -> Path | None:
    blob = bundle.read_bytes()
    if not blob.startswith(MAGIC):
        raise BackupError("not a Mensarium .pab bundle")
    salt, nonce, cipher = blob[4:20], blob[20:32], blob[32:]
    try:
        plain = AESGCM(_key(passphrase, salt)).decrypt(nonce, cipher, MAGIC)
    except InvalidTag as e:
        raise BackupError("wrong passphrase or corrupted bundle") from e
    previous = None
    if paths.root.exists() and any(paths.root.iterdir()):
        previous = paths.root.with_name(f"core.before-restore-{now_iso().replace(':', '')}")
        shutil.move(paths.root, previous)
    paths.ensure()
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz") as tar:
        tar.extractall(paths.root, filter="data")
    for p in paths.secrets.glob("*"):
        p.chmod(0o600)
    return previous
