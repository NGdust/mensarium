import subprocess
import sys
from pathlib import Path
from typing import Any

import httpx

from mensarium.shared.paths import mensarium_home


class ReleaseError(Exception):
    pass


def updater() -> Path | None:
    """`mensarium` of an install.sh setup; a source checkout updates through git instead."""
    venv = (mensarium_home() / "venv").resolve()
    exe = Path(sys.executable).resolve()
    script = Path(sys.executable).parent / "mensarium"
    return script if exe.is_relative_to(venv) and script.exists() else None


async def fetch_latest(base: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=6, follow_redirects=True) as client:
            resp = await client.get(f"{base.rstrip('/')}/dist/latest.json")
            resp.raise_for_status()
            data: dict[str, Any] = resp.json()
    except (httpx.HTTPError, ValueError) as e:
        raise ReleaseError(f"cannot read {base}/dist/latest.json: {e}") from e
    if "version" not in data:
        raise ReleaseError("latest.json has no version")
    return data


def spawn_update(script: Path, source: str) -> None:
    """Detached `mensarium update`: it installs the release and restarts this service."""
    subprocess.Popen([str(script), "update", "--source", source], start_new_session=True)
