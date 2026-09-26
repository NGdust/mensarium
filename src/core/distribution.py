import hashlib
import io
import os
import re
import tarfile
from functools import lru_cache
from pathlib import Path

from mensarium.shared.paths import mensarium_home

INCLUDE = ("pyproject.toml", "install.sh", "README.md", "src")


def source_dir() -> Path | None:
    candidates = [
        os.environ.get("MENSARIUM_SOURCE_DIR"),
        str(mensarium_home() / "src"),
        str(Path(__file__).resolve().parents[2]),
    ]
    for c in candidates:
        if c and (Path(c) / "pyproject.toml").exists() and (Path(c) / "install.sh").exists():
            return Path(c)
    return None


def install_script(server_url: str) -> str:
    """install.sh that fetches the package from this Core, so clients get the Core's own version."""
    src = source_dir()
    if src is None:
        raise FileNotFoundError("install.sh not found")
    text = (src / "install.sh").read_text()
    return re.sub(r'(?m)^MENSARIUM_SOURCE_DEFAULT=".*"$', f'MENSARIUM_SOURCE_DEFAULT="{server_url.rstrip("/")}/dist/mensarium.tar.gz"', text, count=1)


def _skip(info: tarfile.TarInfo) -> tarfile.TarInfo | None:
    name = Path(info.name).name
    if name in ("__pycache__", ".DS_Store") or name.endswith(".pyc"):
        return None
    return info


@lru_cache(maxsize=1)
def source_tarball() -> bytes:
    src = source_dir()
    if src is None:
        raise FileNotFoundError("source directory not found")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for item in INCLUDE:
            if (src / item).exists():
                tar.add(src / item, arcname=f"mensarium/{item}", filter=_skip)
    return buf.getvalue()


def latest_manifest(version: str) -> dict[str, str]:
    return {"version": version, "file": "mensarium.tar.gz", "sha256": hashlib.sha256(source_tarball()).hexdigest()}
