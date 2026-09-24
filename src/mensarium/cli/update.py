import hashlib
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any

import httpx

from mensarium import __version__
from mensarium.cli import service
from mensarium.core.config import CorePaths
from mensarium.shared.paths import mensarium_home
from mensarium.target.config import TargetPaths, load_target_config

DEFAULT_UPDATE_URL = "https://mensarium.com"


class UpdateError(Exception):
    pass


def parse_version(value: str) -> tuple[int, ...]:
    return tuple(int(p) for p in value.split(".") if p.isdigit())


def update_source() -> str:
    """Core updates from the public site; a target follows its own Core to stay on the same version."""
    if env := os.environ.get("MENSARIUM_UPDATE_URL"):
        return env.rstrip("/")
    if not CorePaths().config.exists() and TargetPaths().config.exists():
        return load_target_config(TargetPaths()).server.rstrip("/")
    return DEFAULT_UPDATE_URL


def fetch_latest(base: str, timeout: float = 15) -> dict[str, Any]:
    try:
        resp = httpx.get(f"{base}/dist/latest.json", timeout=timeout, follow_redirects=True)
        resp.raise_for_status()
        data: dict[str, Any] = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise UpdateError(f"cannot read {base}/dist/latest.json: {e}") from e
    if "version" not in data:
        raise UpdateError("latest.json has no version")
    return data


def is_newer(latest: str, current: str = __version__) -> bool:
    return parse_version(latest) > parse_version(current)


def _uv() -> str:
    uv = shutil.which("uv") or str(mensarium_home() / "bin" / "uv")
    if not Path(uv).exists():
        raise UpdateError("uv not found; re-run the installer: curl -fsSL https://mensarium.com/install.sh | sh")
    return uv


def install(base: str, latest: dict[str, Any]) -> list[str]:
    url = f"{base}/dist/{latest.get('file', 'mensarium.tar.gz')}"
    try:
        resp = httpx.get(url, timeout=120, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise UpdateError(f"download failed: {e}") from e
    data = resp.content
    if latest.get("sha256") and hashlib.sha256(data).hexdigest() != latest["sha256"]:
        raise UpdateError("checksum mismatch: the downloaded archive differs from latest.json")

    src = mensarium_home() / "src"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "src.tar.gz"
        archive.write_bytes(data)
        with tarfile.open(archive) as tar:
            tar.extractall(tmp, filter="data")
        found = next(Path(tmp).glob("*/pyproject.toml"), None)
        if found is None:
            raise UpdateError("archive has no pyproject.toml")
        if src.exists():
            shutil.rmtree(src)
        shutil.move(str(found.parent), src)

    result = subprocess.run(
        [_uv(), "pip", "install", "--quiet", "--python", sys.executable, "--reinstall-package", "mensarium", str(src)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise UpdateError(f"install failed: {result.stderr.strip()[-800:]}")

    restarted = []
    configured = {"core": CorePaths().config.exists(), "target": TargetPaths().config.exists()}
    for role in ("core", "target"):
        if configured[role] and service.is_installed(role):  # type: ignore[arg-type]
            service.restart(role)  # type: ignore[arg-type]
            restarted.append(role)
    return restarted
