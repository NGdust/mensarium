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

CLAUDE_MODELS = ["claude-fable-5-1", "claude-opus-5", "claude-sonnet-5", "claude-haiku-4-5"]
CLAUDE_DEFAULT_MODEL = "claude-sonnet-5"
CLAUDE_PROBE_MODEL = "claude-haiku-4-5"
CODEX_MODELS = ["gpt-5-codex", "gpt-5"]
RPC_TIMEOUT_S = 30
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


def codex_rpc(command: str, method: str, params: dict[str, Any] | None = None, cwd: str | None = None) -> dict[str, Any]:
    """One request to `codex app-server` over stdio (JSONL): initialize, initialized, then the method. Blocking."""
    import select

    messages = [
        {"id": 1, "method": "initialize", "params": {"clientInfo": {"name": "mensarium", "version": "1"}}},
        {"method": "initialized"},
        {"id": 2, "method": method, "params": params or {}},
    ]
    proc = subprocess.Popen(
        [command, "app-server", "--stdio"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, cwd=cwd
    )
    assert proc.stdin and proc.stdout
    try:
        for m in messages:
            proc.stdin.write(json.dumps(m) + "\n")
        proc.stdin.flush()
        deadline = time.monotonic() + RPC_TIMEOUT_S
        while time.monotonic() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 1)
            if not ready:
                continue
            line = proc.stdout.readline()
            if not line:
                break
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if msg.get("id") == 2:
                if msg.get("error"):
                    raise RuntimeError(str(msg["error"].get("message") or msg["error"]))
                result: dict[str, Any] = msg.get("result") or {}
                return result
        raise RuntimeError("codex app-server did not answer")
    finally:
        proc.kill()
        proc.wait()


def codex_models(command: str) -> list[str]:
    """Models the logged-in Codex account can use, from the app-server; the config default first."""
    try:
        data = codex_rpc(command, "model/list").get("data") or []
        models = [str(m.get("id") or m.get("model")) for m in data if not m.get("hidden") and (m.get("id") or m.get("model"))]
    except (OSError, RuntimeError):
        models = []
    default = codex_config_model()
    ordered = ([default] if default else []) + models + (CODEX_MODELS if not models else [])
    return list(dict.fromkeys(ordered))


def codex_config_model() -> str:
    cfg = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser() / "config.toml"
    if cfg.exists():
        m = re.search(r'(?m)^model\s*=\s*"([^"]+)"', cfg.read_text(errors="replace"))
        if m:
            return m.group(1)
    return ""


def _claude(path: str) -> LocalCli:
    cli = LocalCli(kind="claude_code", title="Claude Code", path=path, models=list(CLAUDE_MODELS), default_model=CLAUDE_DEFAULT_MODEL)
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
    models = codex_models(path)
    cli = LocalCli(kind="codex_cli", title="Codex CLI", path=path, models=models, default_model=models[0])
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
