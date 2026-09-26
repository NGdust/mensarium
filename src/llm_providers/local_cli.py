"""Finds the Claude Code and Codex command-line agents installed on the Core host."""

import asyncio
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

CLAUDE_MODELS = ["sonnet", "opus", "haiku"]
CODEX_MODELS = ["gpt-5-codex", "gpt-5"]
CANDIDATE_DIRS = (
    "~/.local/bin", "~/.claude/local", "~/.claude/bin", "/opt/homebrew/bin", "/usr/local/bin", "~/.npm-global/bin",
    "~/.volta/bin", "~/.bun/bin", "~/.cargo/bin",
)  # fmt: skip
CACHE_TTL_S = 60


@dataclass
class LocalCli:
    kind: str
    title: str
    path: str
    version: str = ""
    logged_in: bool | None = None
    account: str = ""
    default_model: str = ""
    models: list[str] = field(default_factory=list)

    def view(self) -> dict[str, Any]:
        return asdict(self)


def _which(name: str) -> str | None:
    if found := shutil.which(name):
        return found
    for d in CANDIDATE_DIRS:
        p = Path(d).expanduser() / name
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    nvm = Path("~/.nvm/versions/node").expanduser()
    if nvm.is_dir():
        for p in sorted(nvm.glob(f"*/bin/{name}"), reverse=True):
            if os.access(p, os.X_OK):
                return str(p)
    return None


def _run(*cmd: str, timeout: float = 10) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return r.returncode, (r.stdout + r.stderr).strip()


def codex_config_model() -> str:
    cfg = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "config.toml"
    if cfg.exists():
        m = re.search(r'(?m)^model\s*=\s*"([^"]+)"', cfg.read_text(errors="replace"))
        if m:
            return m.group(1)
    return ""


def _claude(path: str) -> LocalCli:
    cli = LocalCli(kind="claude_code", title="Claude Code", path=path, models=list(CLAUDE_MODELS), default_model="sonnet")
    code, out = _run(path, "--version")
    cli.version = out.split()[0] if code == 0 and out else ""
    code, out = _run(path, "auth", "status")
    try:
        status = json.loads(out[out.index("{") :]) if code == 0 and "{" in out else {}
    except (ValueError, json.JSONDecodeError):
        status = {}
    if status:
        cli.logged_in = bool(status.get("loggedIn"))
        cli.account = str(status.get("email") or status.get("authMethod") or "")
    return cli


def _codex(path: str) -> LocalCli:
    default = codex_config_model()
    models = [default, *CODEX_MODELS] if default else list(CODEX_MODELS)
    cli = LocalCli(kind="codex_cli", title="Codex CLI", path=path, models=list(dict.fromkeys(models)), default_model=models[0])
    code, out = _run(path, "--version")
    cli.version = out.replace("codex-cli", "").strip().split()[0] if code == 0 and out else ""
    code, out = _run(path, "login", "status")
    if code == 0:
        cli.logged_in = "logged in" in out.lower()
        cli.account = out.strip().splitlines()[0] if cli.logged_in else ""
    elif out:
        cli.logged_in = False
    return cli


def detect_local_clis() -> list[LocalCli]:
    """Blocking; each probe runs the CLI a couple of times, so callers cache the result."""
    found = []
    if path := _which("claude"):
        found.append(_claude(path))
    if path := _which("codex"):
        found.append(_codex(path))
    return found


_cache: tuple[float, list[LocalCli]] | None = None
_lock = asyncio.Lock()


async def detect_local_clis_cached(force: bool = False) -> list[LocalCli]:
    global _cache
    async with _lock:
        if _cache and not force and time.monotonic() - _cache[0] < CACHE_TTL_S:
            return _cache[1]
        found = await asyncio.to_thread(detect_local_clis)
        _cache = (time.monotonic(), found)
        return found
