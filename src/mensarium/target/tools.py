import asyncio
import os
import re
import shlex
import shutil
import signal
from pathlib import Path
from typing import Any

from mensarium.contracts.protocol import ToolOutput
from mensarium.contracts.tools import (
    FilesListArgs,
    FilesReadArgs,
    FilesSearchArgs,
    GitDiffArgs,
    GitStatusArgs,
    ShellExecArgs,
)
from mensarium.shared.redaction import SECRET_DIRS, SECRET_FILE_PATTERNS, is_secret_path, redact
from mensarium.target.config import TargetConfig

MAX_READ_BYTES = 2_000_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build", ".next", ".idea"}  # fmt: skip
SECRET_ENV = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|PRIVATE|CREDENTIAL|_KEY$)", re.I)


class ToolError(Exception):
    pass


class Executor:
    def __init__(self, cfg: TargetConfig) -> None:
        self.cfg = cfg
        self.roots = [Path(r).expanduser().resolve() for r in cfg.roots]

    def _path(self, value: str) -> Path:
        p = Path(value).expanduser()
        if not p.is_absolute():
            p = self.roots[0] / p
        resolved = p.resolve()
        if not any(resolved == r or resolved.is_relative_to(r) for r in self.roots):
            raise ToolError(f"path {value!r} resolves outside the allowed roots")
        return resolved

    def _limit(self, text: str) -> tuple[str, bool]:
        limit = self.cfg.limits.max_stdout_bytes
        data = text.encode()
        if len(data) <= limit:
            return text, False
        return data[:limit].decode(errors="ignore") + "\n...[truncated by target]", True

    async def run(self, tool: str, args: dict[str, Any]) -> ToolOutput:
        handler = {
            "files.list": self.files_list,
            "files.read": self.files_read,
            "files.search": self.files_search,
            "git.status": self.git_status,
            "git.diff": self.git_diff,
            "shell.exec": self.shell_exec,
        }.get(tool)
        if handler is None:
            raise ToolError(f"unsupported tool {tool!r}")
        return await handler(args)

    async def files_list(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesListArgs.model_validate(raw)
        base = self._path(a.path)
        if not base.is_dir():
            raise ToolError(f"{a.path} is not a directory")
        lines: list[str] = []

        def walk(d: Path, depth: int, prefix: str) -> None:
            try:
                entries = sorted(d.iterdir(), key=lambda e: (not e.is_dir(), e.name))
            except PermissionError:
                return
            for e in entries:
                if len(lines) >= 1000:
                    return
                if e.is_dir():
                    lines.append(f"{prefix}{e.name}/")
                    if depth > 1 and e.name not in SKIP_DIRS and e.name not in SECRET_DIRS:
                        walk(e, depth - 1, prefix + "  ")
                else:
                    lines.append(f"{prefix}{e.name}")

        await asyncio.to_thread(walk, base, a.depth, "")
        text = f"{base}/\n" + "\n".join(lines) + ("\n...[listing capped at 1000 entries]" if len(lines) >= 1000 else "")
        return ToolOutput(exit_code=0, stdout=text)

    async def files_read(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesReadArgs.model_validate(raw)
        path = self._path(a.path)
        if is_secret_path(str(path)):
            raise ToolError("reading secret files is not allowed")
        if not path.is_file():
            raise ToolError(f"{a.path} is not a file")
        if path.stat().st_size > MAX_READ_BYTES:
            raise ToolError(f"file is larger than {MAX_READ_BYTES} bytes")
        data = await asyncio.to_thread(path.read_bytes)
        if b"\0" in data[:8192]:
            raise ToolError("binary file")
        all_lines = data.decode(errors="replace").splitlines()
        chunk = all_lines[a.start_line - 1 : a.start_line - 1 + a.max_lines]
        end = a.start_line + len(chunk) - 1
        width = len(str(end))
        body = "\n".join(f"{i:>{width}}| {line}" for i, line in enumerate(chunk, a.start_line))
        header = f"{path} (lines {a.start_line}-{end} of {len(all_lines)})\n"
        text, truncated = self._limit(header + redact(body))
        return ToolOutput(exit_code=0, stdout=text, truncated=truncated or end < len(all_lines))

    async def files_search(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesSearchArgs.model_validate(raw)
        base = self._path(a.path)
        rg = shutil.which("rg")
        if rg:
            argv = [rg, "--line-number", "--no-heading", "--color", "never", "--max-columns", "300", "--max-filesize", "2M"]
            if not a.regex:
                argv.append("--fixed-strings")
            if a.glob:
                argv += ["--glob", a.glob]
            for pat in SECRET_FILE_PATTERNS:
                argv += ["--glob", f"!{pat}"]
            for d in SECRET_DIRS:
                argv += ["--glob", f"!{d}/"]
            argv += ["--", a.query, str(base)]
            code, out, err = await _run(argv, cwd=base, timeout=60)
            if code not in (0, 1):
                raise ToolError(f"rg failed: {err.strip()}")
            lines = out.splitlines()
        else:
            lines = await asyncio.to_thread(_py_search, base, a)
        shown = lines[: a.max_results]
        text = "\n".join(shown) or "(no matches)"
        if len(lines) > a.max_results:
            text += f"\n...[{len(lines) - a.max_results} more matches]"
        text, truncated = self._limit(redact(text))
        return ToolOutput(exit_code=0, stdout=text, truncated=truncated)

    async def _git(self, repo: str, *args: str) -> ToolOutput:
        cwd = self._path(repo)
        if not cwd.is_dir():
            cwd = cwd.parent
        git = shutil.which("git")
        if not git:
            raise ToolError("git is not installed")
        code, out, err = await _run([git, "-c", "color.ui=never", *args], cwd=cwd, timeout=60)
        text, truncated = self._limit(redact(out))
        return ToolOutput(exit_code=code, stdout=text, stderr=redact(err), truncated=truncated)

    async def git_status(self, raw: dict[str, Any]) -> ToolOutput:
        a = GitStatusArgs.model_validate(raw)
        return await self._git(a.repo, "status", "--short", "--branch")

    async def git_diff(self, raw: dict[str, Any]) -> ToolOutput:
        a = GitDiffArgs.model_validate(raw)
        args = ["diff"] + (["--staged"] if a.staged else [])
        if a.path:
            args += ["--", str(self._path(a.path))]
        return await self._git(a.repo, *args)

    async def shell_exec(self, raw: dict[str, Any]) -> ToolOutput:
        a = ShellExecArgs.model_validate(raw)
        cwd = self._path(a.cwd)
        if not cwd.is_dir():
            raise ToolError(f"cwd {a.cwd} is not a directory")
        argv = shlex.split(a.command)
        if not argv:
            raise ToolError("empty command")
        allow = self.cfg.command_allowlist
        if "*" not in allow and ("/" in argv[0] or argv[0] not in allow):
            raise ToolError(f"program {argv[0]!r} is not in the target command allowlist")
        program = shutil.which(argv[0], path=os.environ.get("PATH"))
        if program is None and "/" not in argv[0]:
            raise ToolError(f"program {argv[0]!r} not found on PATH")
        timeout = min(a.timeout_s, self.cfg.limits.max_exec_seconds)
        env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
        code, out, err = await _run([program or argv[0], *argv[1:]], cwd=cwd, timeout=timeout, stdin=a.stdin, env=env)
        out, t1 = self._limit(redact(out))
        err, t2 = self._limit(redact(err))
        return ToolOutput(exit_code=code, stdout=out, stderr=err, truncated=t1 or t2)


class ExecTimeout(Exception):
    pass


async def _run(
    argv: list[str],
    *,
    cwd: Path,
    timeout: float,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin.encode() if stdin is not None else None), timeout)
    except (TimeoutError, asyncio.CancelledError) as e:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        if isinstance(e, TimeoutError):
            raise ExecTimeout(f"command timed out after {timeout}s") from e
        raise
    return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")


def _py_search(base: Path, a: FilesSearchArgs) -> list[str]:
    import fnmatch

    pattern = re.compile(a.query if a.regex else re.escape(a.query))
    out: list[str] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and d not in SECRET_DIRS]
        for name in files:
            if a.glob and not fnmatch.fnmatch(name, a.glob):
                continue
            path = Path(root) / name
            if is_secret_path(str(path)):
                continue
            try:
                with path.open(errors="replace") as f:
                    for i, line in enumerate(f, 1):
                        if pattern.search(line):
                            out.append(f"{path}:{i}:{line.rstrip()[:300]}")
                            if len(out) > a.max_results * 2:
                                return out
            except (OSError, UnicodeDecodeError):
                continue
    return out
