"""Git bundles travel as base64 chunks inside WebSocket frames; both the Core and the client assemble them here."""

import base64
import hashlib
import os
from collections.abc import Iterator
from pathlib import Path

from mensarium.contracts.projects import BundleInfo
from mensarium.shared.paths import ensure_private_dir

CHUNK = 512 * 1024
LIMIT = 2 * 1024**3


class BundleTooLarge(Exception):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def chunks(path: Path) -> Iterator[str]:
    with path.open("rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            yield base64.b64encode(block).decode()


def append_chunk(path: Path, data_b64: str) -> None:
    raw = base64.b64decode(data_b64, validate=True)
    ensure_private_dir(path.parent)
    size = path.stat().st_size if path.exists() else 0
    if size + len(raw) > LIMIT:
        path.unlink(missing_ok=True)
        raise BundleTooLarge(f"bundle is above {LIMIT // 1024**3} GiB")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "ab") as f:
        f.write(raw)


def describe(path: Path, refs: dict[str, str], prerequisites: list[str]) -> BundleInfo:
    return BundleInfo(sha256=sha256_file(path), size=path.stat().st_size, refs=refs, prerequisites=prerequisites)


def check(path: Path, info: BundleInfo) -> None:
    if not path.is_file() or path.stat().st_size != info.size:
        raise ValueError("bundle size does not match")
    if sha256_file(path) != info.sha256:
        raise ValueError("bundle checksum does not match")
