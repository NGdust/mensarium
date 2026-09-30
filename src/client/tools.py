import asyncio
import difflib
import fnmatch
import logging
import os
import platform
import re
import shlex
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from mensarium import __version__
from mensarium.client import desktop
from mensarium.client.config import ClientConfig
from mensarium.client.desktop import DesktopError
from mensarium.client.undo import UndoError, UndoSlot, apply_undo
from mensarium.contracts.protocol import AccessMode, ToolOutput
from mensarium.contracts.tools import (
    AppOpenArgs,
    FilesCopyArgs,
    FilesDeleteArgs,
    FilesEditArgs,
    FilesFindArgs,
    FilesListArgs,
    FilesMkdirArgs,
    FilesMoveArgs,
    FilesReadArgs,
    FilesSearchArgs,
    FilesStatArgs,
    FilesWriteArgs,
    GitDiffArgs,
    GitStatusArgs,
    InputKeyArgs,
    InputMouseArgs,
    InputTypeArgs,
    NetHttpArgs,
    ProcessKillArgs,
    ProcessListArgs,
    ScreenCaptureArgs,
    ShellBashArgs,
    ShellExecArgs,
    SystemVolumeArgs,
    UndoApplyArgs,
)
from mensarium.shared.gitflags import GIT_SAFE_FLAGS
from mensarium.shared.paths import client_dir, ensure_private_dir, projects_dir
from mensarium.shared.redaction import GIT_DIRS, SECRET_DIRS, SECRET_FILE_PATTERNS, is_secret_path, redact
from mensarium.shared.secret_refs import mask_secrets
from mensarium.tool_runtime.mcp import McpError

if TYPE_CHECKING:
    from mensarium.client.mcp_host import McpHost

MAX_READ_BYTES = 2_000_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".ruff_cache", ".pytest_cache", "dist", "build", ".next", ".idea"}  # fmt: skip
SECRET_ENV = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|APIKEY|PRIVATE|CREDENTIAL|_KEY$)", re.I)
log = logging.getLogger(__name__)

_FULL_ACCESS: ContextVar[bool] = ContextVar("mensarium_full_access", default=False)
_WORKDIR: ContextVar[Path | None] = ContextVar("mensarium_workdir", default=None)
_SECRETS: ContextVar[dict[str, str] | None] = ContextVar("mensarium_secrets", default=None)
_UNDO: ContextVar[UndoSlot | None] = ContextVar("mensarium_undo", default=None)


class ToolError(Exception):
    pass


def _remember(action: Callable[[UndoSlot], None]) -> None:
    """Save the pre-state for the undo slot of this call; a slot that cannot be written only makes the call non-undoable."""
    slot = _UNDO.get()
    if slot is None or slot.disabled:
        return
    try:
        action(slot)
    except (OSError, UndoError, subprocess.SubprocessError) as e:
        log.warning("undo slot not saved", extra={"tool": slot.tool, "error": str(e)})
        slot.disabled = True


class Executor:
    def __init__(self, cfg: ClientConfig) -> None:
        self.cfg = cfg
        self.projects_root = ensure_private_dir(projects_dir()).resolve()
        self.roots = [Path(r).expanduser().resolve() for r in cfg.roots]
        if not any(self.projects_root == r or self.projects_root.is_relative_to(r) for r in self.roots):
            self.roots.append(self.projects_root)
        self.mcp: McpHost | None = None
        self.undo_root = client_dir() / "undo"

    def _path(self, value: str) -> Path:
        p = Path(value).expanduser()
        if not p.is_absolute():
            p = (_WORKDIR.get() or self.roots[0]) / p
        resolved = p.resolve()
        if not _FULL_ACCESS.get() and not any(resolved == r or resolved.is_relative_to(r) for r in self.roots):
            raise ToolError(f"path {value!r} resolves outside the allowed roots")
        return resolved

    def _is_secret(self, path: Path) -> bool:
        if _FULL_ACCESS.get():
            return False
        if path.is_relative_to(self.projects_root):
            rel = path.relative_to(self.projects_root)
            return any(part.lower() in GIT_DIRS for part in rel.parts) or is_secret_path(str(rel))
        return is_secret_path(str(path))

    def workdir(self, value: str) -> Path:
        resolved = Path(value).expanduser().resolve()
        if not any(resolved == r or resolved.is_relative_to(r) for r in self.roots):
            raise ToolError("workdir must be inside the allowed folders of this device")
        if not resolved.is_dir():
            raise ToolError("workdir does not exist on this device")
        return resolved

    def _limit(self, text: str) -> tuple[str, bool]:
        limit = self.cfg.limits.max_stdout_bytes
        data = text.encode()
        if len(data) <= limit:
            return text, False
        return data[:limit].decode(errors="ignore") + "\n...[truncated by target]", True

    async def run(
        self,
        tool: str,
        args: dict[str, Any],
        workdir: Path | None = None,
        *,
        mode: AccessMode = "ask",
        secrets: dict[str, str] | None = None,
        undo: UndoSlot | None = None,
    ) -> ToolOutput:
        if mode == "full" and not self.cfg.allow_full_access:
            raise ToolError("full access is disabled on this device")
        access_token = _FULL_ACCESS.set(mode == "full")
        token = _WORKDIR.set(workdir)
        secrets_token = _SECRETS.set(secrets or {})
        undo_token = _UNDO.set(undo)
        try:
            handler = {
                "files.list": self.files_list,
                "files.read": self.files_read,
                "files.search": self.files_search,
                "files.stat": self.files_stat,
                "files.find": self.files_find,
                "files.write": self.files_write,
                "files.edit": self.files_edit,
                "files.mkdir": self.files_mkdir,
                "files.move": self.files_move,
                "files.copy": self.files_copy,
                "files.delete": self.files_delete,
                "git.status": self.git_status,
                "git.diff": self.git_diff,
                "system.info": self.system_info,
                "process.list": self.process_list,
                "process.kill": self.process_kill,
                "net.ports": self.net_ports,
                "net.http": self.net_http,
                "shell.exec": self.shell_exec,
                "shell.bash": self.shell_bash,
                "screen.capture": self.screen_capture,
                "screen.windows": self.screen_windows,
                "input.mouse": self.input_mouse,
                "input.type": self.input_type,
                "input.key": self.input_key,
                "app.open": self.app_open,
                "system.volume": self.system_volume,
                "mcp.call": self.mcp_call,
                "undo.apply": self.undo_apply,
            }.get(tool)
            if handler is None:
                raise ToolError(f"unsupported tool {tool!r}")
            try:
                output = await handler(args)
            except (DesktopError, ToolError) as e:
                if undo:
                    undo.discard()
                raise ToolError(mask_secrets(str(e), secrets or {})) from None
            except (ExecTimeout, asyncio.CancelledError):
                if undo:
                    undo.commit()  # the command may have changed things halfway; keep what we saved
                raise
            except Exception as e:
                if undo:
                    undo.discard()
                if not secrets:
                    raise
                raise ToolError(f"{type(e).__name__}: details hidden because the request carries secrets") from None
            if undo:
                output.undo = undo.commit()
            if secrets:
                output.stdout = mask_secrets(output.stdout, secrets)
                output.stderr = mask_secrets(output.stderr, secrets)
            return output
        finally:
            _UNDO.reset(undo_token)
            _SECRETS.reset(secrets_token)
            _WORKDIR.reset(token)
            _FULL_ACCESS.reset(access_token)

    @staticmethod
    def _redact(text: str) -> str:
        text = mask_secrets(text, _SECRETS.get() or {})
        return text if _FULL_ACCESS.get() else redact(text)

    @staticmethod
    def _env() -> dict[str, str]:
        env = dict(os.environ) if _FULL_ACCESS.get() else {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
        return {**env, **(_SECRETS.get() or {})}

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
                    if depth > 1 and e.name not in SKIP_DIRS and (e.name not in SECRET_DIRS or _FULL_ACCESS.get()):
                        walk(e, depth - 1, prefix + "  ")
                else:
                    lines.append(f"{prefix}{e.name}")

        await asyncio.to_thread(walk, base, a.depth, "")
        text = f"{base}/\n" + "\n".join(lines) + ("\n...[listing capped at 1000 entries]" if len(lines) >= 1000 else "")
        return ToolOutput(exit_code=0, stdout=text)

    async def files_read(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesReadArgs.model_validate(raw)
        path = self._path(a.path)
        if self._is_secret(path):
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
        text, truncated = self._limit(header + self._redact(body))
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
            if _FULL_ACCESS.get():
                argv.append("--hidden")
            for pat in (() if _FULL_ACCESS.get() else SECRET_FILE_PATTERNS):
                argv += ["--glob", f"!{pat}"]
            for d in (() if _FULL_ACCESS.get() else SECRET_DIRS):
                argv += ["--glob", f"!{d}/"]
            argv += ["--", a.query, str(base)]
            code, out, err = await _run(argv, cwd=base, timeout=60)
            if code not in (0, 1):
                raise ToolError(f"rg failed: {err.strip()}")
            lines = out.splitlines()
        else:
            lines = await asyncio.to_thread(_py_search, base, a, self._is_secret)
        shown = lines[: a.max_results]
        text = "\n".join(shown) or "(no matches)"
        if len(lines) > a.max_results:
            text += f"\n...[{len(lines) - a.max_results} more matches]"
        text, truncated = self._limit(self._redact(text))
        return ToolOutput(exit_code=0, stdout=text, truncated=truncated)

    async def _git(self, repo: str, *args: str) -> ToolOutput:
        cwd = self._path(repo)
        if not cwd.is_dir():
            cwd = cwd.parent
        git = shutil.which("git")
        if not git:
            raise ToolError("git is not installed")
        code, out, err = await _run([git, *GIT_SAFE_FLAGS, *args], cwd=cwd, timeout=60)
        text, truncated = self._limit(self._redact(out))
        return ToolOutput(exit_code=code, stdout=text, stderr=self._redact(err), truncated=truncated)

    async def git_status(self, raw: dict[str, Any]) -> ToolOutput:
        a = GitStatusArgs.model_validate(raw)
        return await self._git(a.repo, "status", "--short", "--branch")

    async def git_diff(self, raw: dict[str, Any]) -> ToolOutput:
        a = GitDiffArgs.model_validate(raw)
        args = ["diff"] + (["--staged"] if a.staged else [])
        if a.path:
            args += ["--", str(self._path(a.path))]
        return await self._git(a.repo, *args)

    async def mcp_call(self, raw: dict[str, Any]) -> ToolOutput:
        if self.mcp is None:
            raise ToolError("MCP servers are not available on this device")
        args = raw.get("arguments")
        if not isinstance(args, dict):
            raise ToolError("arguments must be a JSON object")
        try:
            text, is_error = await self.mcp.call(str(raw.get("server")), str(raw.get("tool")), args, self.cfg.limits.max_exec_seconds)
        except McpError as e:
            raise ToolError(str(e)) from e
        out, truncated = self._limit(self._redact(text))
        return ToolOutput(exit_code=1 if is_error else 0, stdout=out, truncated=truncated)

    # ---- files: metadata and writing -----------------------------------------

    def _writable(self, value: str) -> Path:
        path = self._path(value)
        if self._is_secret(path):
            raise ToolError("secret files and folders cannot be changed")
        return path

    @staticmethod
    def _read_text(path: Path) -> str:
        data = path.read_bytes()
        if b"\0" in data[:8192]:
            raise ToolError("binary file")
        if len(data) > MAX_READ_BYTES:
            raise ToolError(f"file is larger than {MAX_READ_BYTES} bytes")
        return data.decode("utf-8", errors="surrogateescape")

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        mode = path.stat().st_mode if path.exists() else None
        fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(text.encode("utf-8", errors="surrogateescape"))
            if mode is not None:
                os.chmod(tmp, stat.S_IMODE(mode))
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    async def files_stat(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesStatArgs.model_validate(raw)
        path = self._path(a.path)
        if self._is_secret(path):
            raise ToolError("access to secret files is not allowed")
        if not path.exists():
            raise ToolError(f"{a.path} does not exist")
        st = path.lstat()
        kind = "symlink" if stat.S_ISLNK(st.st_mode) else "directory" if path.is_dir() else "file"
        lines = [f"{path}", f"type: {kind}", f"size: {st.st_size} bytes", f"mode: {stat.filemode(st.st_mode)}",
                 f"modified: {datetime.fromtimestamp(st.st_mtime).isoformat(timespec='seconds')}"]
        if kind == "file":
            try:
                data = await asyncio.to_thread(path.read_bytes) if st.st_size <= MAX_READ_BYTES else b""
                lines.append("binary: yes" if b"\0" in data[:8192] else f"lines: {data.count(b'\n') + (1 if data and not data.endswith(b'\n') else 0)}")
            except OSError as e:
                lines.append(f"unreadable: {e.strerror}")
        elif kind == "directory":
            try:
                entries = list(path.iterdir())
                lines.append(f"entries: {len(entries)}")
            except PermissionError:
                lines.append("entries: (permission denied)")
        return ToolOutput(exit_code=0, stdout="\n".join(lines))

    async def files_find(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesFindArgs.model_validate(raw)
        base = self._path(a.path)
        if not base.is_dir():
            raise ToolError(f"{a.path} is not a directory")
        matcher = _glob_regex(a.pattern)
        by_name = "/" not in a.pattern

        def walk() -> tuple[list[str], bool]:
            out: list[str] = []
            for root, dirs, files in os.walk(base):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and (d not in SECRET_DIRS or _FULL_ACCESS.get()) and (a.include_hidden or not d.startswith(".")))
                for name in sorted(files):
                    rel = os.path.relpath(os.path.join(root, name), base)
                    if not a.include_hidden and name.startswith("."):
                        continue
                    if self._is_secret(base / rel):
                        continue
                    if matcher.match(name if by_name else rel):
                        out.append(rel)
                        if len(out) > a.max_results:
                            return out[: a.max_results], True
            return out, False

        found, more = await asyncio.to_thread(walk)
        text = "\n".join(found) or "(no matches)"
        if more:
            text += f"\n...[more than {a.max_results} matches, narrow the pattern]"
        return ToolOutput(exit_code=0, stdout=text)

    async def files_write(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesWriteArgs.model_validate(raw)
        path = self._writable(a.path)
        if path.is_dir():
            raise ToolError(f"{a.path} is a directory")
        _remember(lambda slot: slot.file(path))
        before = None
        if path.exists():
            before = await asyncio.to_thread(self._read_text, path)
        elif a.create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        elif not path.parent.is_dir():
            raise ToolError(f"directory {path.parent} does not exist")
        await asyncio.to_thread(self._write_atomic, path, a.content)
        new_lines = a.content.count("\n") + (1 if a.content and not a.content.endswith("\n") else 0)
        if before is None:
            return ToolOutput(exit_code=0, stdout=f"created {path} ({new_lines} lines)")
        added, removed = _diff_counts(before, a.content)
        return ToolOutput(exit_code=0, stdout=f"overwrote {path}: {new_lines} lines now, +{added} -{removed} vs the previous version")

    async def files_edit(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesEditArgs.model_validate(raw)
        path = self._writable(a.path)
        if not path.is_file():
            raise ToolError(f"{a.path} is not a file")
        text = await asyncio.to_thread(self._read_text, path)
        count = text.count(a.old)
        if count == 0:
            raise ToolError("`old` was not found in the file; read the file again and copy the fragment exactly, including whitespace")
        if count > 1 and not a.replace_all:
            raise ToolError(f"`old` appears {count} times; include more surrounding lines to make it unique, or set replace_all")
        updated = text.replace(a.old, a.new) if a.replace_all else text.replace(a.old, a.new, 1)
        _remember(lambda slot: slot.file(path))
        await asyncio.to_thread(self._write_atomic, path, updated)
        diff = "".join(difflib.unified_diff(text.splitlines(True), updated.splitlines(True), str(path), str(path), n=2))
        out, truncated = self._limit(self._redact(diff))
        return ToolOutput(exit_code=0, stdout=f"replaced {count if a.replace_all else 1} occurrence(s)\n{out}", truncated=truncated)

    async def files_mkdir(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesMkdirArgs.model_validate(raw)
        path = self._writable(a.path)
        if path.exists() and not path.is_dir():
            raise ToolError(f"{a.path} exists and is not a directory")
        existed = path.is_dir()
        _remember(lambda slot: slot.dir(path))
        path.mkdir(parents=True, exist_ok=True)
        return ToolOutput(exit_code=0, stdout=f"{'already exists' if existed else 'created'} {path}")

    def _pair(self, source: str, destination: str, overwrite: bool) -> tuple[Path, Path]:
        src, dst = self._writable(source), self._writable(destination)
        if not src.exists():
            raise ToolError(f"{source} does not exist")
        if dst.is_dir() and not src.is_dir():
            dst = dst / src.name
        if dst.exists() and not overwrite:
            raise ToolError(f"{dst} already exists; set overwrite to replace it")
        if dst.exists() and dst.is_dir():
            raise ToolError(f"{dst} is a directory and cannot be replaced")
        if src.is_dir() and dst.is_relative_to(src):
            raise ToolError("destination is inside the source directory")
        return src, dst

    async def files_move(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesMoveArgs.model_validate(raw)
        src, dst = self._pair(a.source, a.destination, a.overwrite)
        _remember(lambda slot: slot.move(src, dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(src), str(dst))
        return ToolOutput(exit_code=0, stdout=f"moved {src} -> {dst}")

    async def files_copy(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesCopyArgs.model_validate(raw)
        src, dst = self._pair(a.source, a.destination, a.overwrite)
        _remember(lambda slot: slot.copy(src, dst))
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            await asyncio.to_thread(shutil.copytree, src, dst, dirs_exist_ok=a.overwrite, ignore=None if _FULL_ACCESS.get() else shutil.ignore_patterns(*SECRET_FILE_PATTERNS, *SECRET_DIRS))
        else:
            await asyncio.to_thread(shutil.copy2, src, dst)
        return ToolOutput(exit_code=0, stdout=f"copied {src} -> {dst}")

    async def files_delete(self, raw: dict[str, Any]) -> ToolOutput:
        a = FilesDeleteArgs.model_validate(raw)
        path = self._writable(a.path)
        _remember(lambda slot: slot.dir(path) if path.is_dir() and not path.is_symlink() else slot.file(path))
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            try:
                path.rmdir()
            except OSError as e:
                raise ToolError(f"{a.path} is not empty; delete its contents first or use shell.bash with `rm -r` and approval") from e
        else:
            raise ToolError(f"{a.path} does not exist")
        return ToolOutput(exit_code=0, stdout=f"deleted {path}")

    # ---- system, processes, network -------------------------------------------

    async def system_info(self, raw: dict[str, Any]) -> ToolOutput:
        u = platform.uname()
        lines = [f"os: {u.system} {u.release} ({platform.platform()})", f"arch: {u.machine}", f"hostname: {u.node}",
                 f"user: {os.environ.get('USER') or os.environ.get('LOGNAME') or ''}", f"cpu cores: {os.cpu_count()}",
                 f"python: {platform.python_version()}", f"agent: mensarium {__version__}", f"shell: {os.environ.get('SHELL', '')}"]
        try:
            total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
            lines.append(f"memory: {total / 2**30:.1f} GiB total")
        except (ValueError, OSError, AttributeError):
            pass
        try:
            lines.append("load average: " + ", ".join(f"{x:.2f}" for x in os.getloadavg()))
        except (OSError, AttributeError):
            pass
        for root in self.roots:
            try:
                d = shutil.disk_usage(root)
                lines.append(f"disk {root}: {d.free / 2**30:.1f} GiB free of {d.total / 2**30:.1f} GiB")
            except OSError:
                pass
        if (up := await _uptime_seconds()) is not None:
            lines.append(f"uptime: {int(up // 86400)}d {int(up % 86400 // 3600)}h {int(up % 3600 // 60)}m")
        return ToolOutput(exit_code=0, stdout="\n".join(lines))

    async def process_list(self, raw: dict[str, Any]) -> ToolOutput:
        a = ProcessListArgs.model_validate(raw)
        ps = shutil.which("ps")
        if not ps:
            raise ToolError("ps is not available")
        code, out, err = await _run([ps, "-axo", "pid=,ppid=,user=,pcpu=,pmem=,etime=,command="], cwd=self.roots[0], timeout=30)
        if code != 0:
            raise ToolError(f"ps failed: {err.strip()}")
        rows = [line.rstrip() for line in out.splitlines() if line.strip()]
        needle = (a.filter or "").lower()
        if needle:
            rows = [r for r in rows if needle in r.lower()]
        shown = rows[: a.limit]
        text = "PID PPID USER %CPU %MEM ELAPSED COMMAND\n" + "\n".join(shown) if shown else "(no processes match)"
        if len(rows) > a.limit:
            text += f"\n...[{len(rows) - a.limit} more]"
        text, truncated = self._limit(self._redact(text))
        return ToolOutput(exit_code=0, stdout=text, truncated=truncated)

    async def process_kill(self, raw: dict[str, Any]) -> ToolOutput:
        a = ProcessKillArgs.model_validate(raw)
        if not _FULL_ACCESS.get() and a.pid in (os.getpid(), os.getppid()):
            raise ToolError("refusing to stop the device agent itself")
        ps = shutil.which("ps")
        if not ps:
            raise ToolError("ps is not available")
        code, out, _ = await _run([ps, "-o", "uid=,command=", "-p", str(a.pid)], cwd=self.roots[0], timeout=15)
        if code != 0 or not out.strip():
            raise ToolError(f"no process with pid {a.pid}")
        uid, _, command = out.strip().partition(" ")
        if not _FULL_ACCESS.get() and uid.strip() != str(os.getuid()):
            raise ToolError(f"process {a.pid} belongs to another user")
        try:
            os.kill(a.pid, signal.SIGKILL if a.force else signal.SIGTERM)
        except ProcessLookupError as e:
            raise ToolError(f"no process with pid {a.pid}") from e
        except PermissionError as e:
            raise ToolError(f"not allowed to signal process {a.pid}") from e
        return ToolOutput(exit_code=0, stdout=f"sent {'SIGKILL' if a.force else 'SIGTERM'} to {a.pid} ({command.strip()[:120]})")

    async def net_ports(self, raw: dict[str, Any]) -> ToolOutput:
        if sys.platform == "darwin":
            lsof = shutil.which("lsof")
            if not lsof:
                raise ToolError("lsof is not available")
            argv = [lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "+c", "0"]
        else:
            ss = shutil.which("ss")
            argv = [ss, "-tulpnH"] if ss else [shutil.which("netstat") or "netstat", "-tulpn"]
            if argv[0] is None:
                raise ToolError("neither ss nor netstat is available")
        code, out, err = await _run(argv, cwd=self.roots[0], timeout=30)
        if code not in (0, 1):
            raise ToolError(f"{Path(argv[0]).name} failed: {err.strip()[:200]}")
        text, truncated = self._limit(self._redact(out.strip() or "(no listening ports visible to this user)"))
        return ToolOutput(exit_code=0, stdout=text, truncated=truncated)

    async def net_http(self, raw: dict[str, Any]) -> ToolOutput:
        a = NetHttpArgs.model_validate(raw)
        headers = {k: v for k, v in a.headers.items() if k.lower() not in ("host", "content-length")}
        headers.setdefault("User-Agent", f"Mensarium-device/{__version__}")
        try:
            async with (
                httpx.AsyncClient(timeout=a.timeout_s, follow_redirects=True, max_redirects=5) as client,
                client.stream(a.method, a.url, headers=headers, content=a.body.encode() if a.body is not None else None) as resp,
            ):
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= a.max_chars * 4:
                        break
                body = b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")
                head = [f"{resp.status_code} {resp.reason_phrase} {resp.url}"] + [f"{k}: {v}" for k, v in resp.headers.items() if k.lower() in ("content-type", "content-length", "location", "server", "date")]
        except httpx.HTTPError as e:
            raise ToolError(f"request failed: {e}") from e
        text = "\n".join(head) + "\n\n" + body[: a.max_chars] + ("\n...[truncated]" if len(body) > a.max_chars else "")
        text, truncated = self._limit(self._redact(text))
        return ToolOutput(exit_code=0 if resp.status_code < 400 else 1, stdout=text, truncated=truncated)

    async def shell_bash(self, raw: dict[str, Any]) -> ToolOutput:
        a = ShellBashArgs.model_validate(raw)
        if not self.cfg.allow_shell:
            raise ToolError("the shell is disabled on this device")
        cwd = self._path(a.cwd)
        if not cwd.is_dir():
            raise ToolError(f"cwd {a.cwd} is not a directory")
        shell = shutil.which("bash") or shutil.which("sh")
        if not shell:
            raise ToolError("no bash or sh on this device")
        timeout = min(a.timeout_s, self.cfg.limits.max_exec_seconds)
        await asyncio.to_thread(_remember, lambda slot: slot.tree(cwd))
        code, out, err = await _run([shell, "-c", a.script], cwd=cwd, timeout=timeout, stdin=a.stdin, env=self._env())
        await asyncio.to_thread(_remember, lambda slot: slot.after())
        out, t1 = self._limit(self._redact(out))
        err, t2 = self._limit(self._redact(err))
        return ToolOutput(exit_code=code, stdout=out, stderr=err, truncated=t1 or t2)

    async def undo_apply(self, raw: dict[str, Any]) -> ToolOutput:
        a = UndoApplyArgs.model_validate(raw)
        try:
            restored = await asyncio.to_thread(apply_undo, self.undo_root, a.task_id, a.tool_call_id)
        except (UndoError, OSError, subprocess.SubprocessError) as e:
            raise ToolError(f"rollback failed: {e}") from None
        return ToolOutput(exit_code=0, stdout="restored:\n" + "\n".join(restored))

    # ---- desktop -----------------------------------------------------------------

    async def screen_capture(self, raw: dict[str, Any]) -> ToolOutput:
        a = ScreenCaptureArgs.model_validate(raw)
        image = await desktop.capture(a.display, a.max_width)
        size = f"{image['width']}x{image['height']}" if image.get("width") else "unknown size"
        note = "" if desktop.permissions().get("screen") is not False else " Screen Recording is not granted to the agent on this device, so the image may show only the wallpaper." + desktop.ACCESSIBILITY_HINT
        return ToolOutput(exit_code=0, stdout=f"screenshot of display {a.display}, {size}, coordinates on it map to screen points.{note}", images=[image])

    async def screen_windows(self, raw: dict[str, Any]) -> ToolOutput:
        text, truncated = self._limit(self._redact(await desktop.windows()))
        return ToolOutput(exit_code=0, stdout=text, truncated=truncated)

    async def input_mouse(self, raw: dict[str, Any]) -> ToolOutput:
        a = InputMouseArgs.model_validate(raw)
        return ToolOutput(exit_code=0, stdout=await desktop.mouse(a.action, a.x, a.y, a.scroll))

    async def input_type(self, raw: dict[str, Any]) -> ToolOutput:
        a = InputTypeArgs.model_validate(raw)
        return ToolOutput(exit_code=0, stdout=await desktop.type_text(a.text))

    async def input_key(self, raw: dict[str, Any]) -> ToolOutput:
        a = InputKeyArgs.model_validate(raw)
        return ToolOutput(exit_code=0, stdout=await desktop.key(a.keys))

    async def app_open(self, raw: dict[str, Any]) -> ToolOutput:
        a = AppOpenArgs.model_validate(raw)
        return ToolOutput(exit_code=0, stdout=await desktop.open_target(a.target))

    async def system_volume(self, raw: dict[str, Any]) -> ToolOutput:
        a = SystemVolumeArgs.model_validate(raw)
        if a.action == "set" and a.level is None:
            raise ToolError("set needs `level` from 0 to 100")
        return ToolOutput(exit_code=0, stdout=await desktop.volume(a.action, a.level))

    async def shell_exec(self, raw: dict[str, Any]) -> ToolOutput:
        a = ShellExecArgs.model_validate(raw)
        cwd = self._path(a.cwd)
        if not cwd.is_dir():
            raise ToolError(f"cwd {a.cwd} is not a directory")
        argv = shlex.split(a.command)
        if not argv:
            raise ToolError("empty command")
        allow = ["*"] if _FULL_ACCESS.get() else self.cfg.command_allowlist
        if "*" not in allow and ("/" in argv[0] or argv[0] not in allow):
            raise ToolError(f"program {argv[0]!r} is not in the target command allowlist")
        program = shutil.which(argv[0], path=os.environ.get("PATH"))
        if program is None and "/" not in argv[0]:
            raise ToolError(f"program {argv[0]!r} not found on PATH")
        timeout = min(a.timeout_s, self.cfg.limits.max_exec_seconds)
        await asyncio.to_thread(_remember, lambda slot: slot.tree(cwd))
        code, out, err = await _run([program or argv[0], *argv[1:]], cwd=cwd, timeout=timeout, stdin=a.stdin, env=self._env())
        await asyncio.to_thread(_remember, lambda slot: slot.after())
        out, t1 = self._limit(self._redact(out))
        err, t2 = self._limit(self._redact(err))
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


def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Glob to regex: `**` crosses directories, `*` and `?` stay inside one path segment."""
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif c == "*":
            out, i = out + "[^/]*", i + 1
        elif c == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(c), i + 1
    return re.compile(out + r"\Z")


def _diff_counts(before: str, after: str) -> tuple[int, int]:
    added = removed = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm="", n=0):
        if line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return added, removed


async def _uptime_seconds() -> float | None:
    if sys.platform == "darwin":
        sysctl = shutil.which("sysctl")
        if not sysctl:
            return None
        code, out, _ = await _run([sysctl, "-n", "kern.boottime"], cwd=Path("/"), timeout=10)
        m = re.search(r"sec = (\d+)", out)
        return time.time() - int(m.group(1)) if code == 0 and m else None
    try:
        return float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        return None


def _py_search(base: Path, a: FilesSearchArgs, is_secret: Callable[[Path], bool]) -> list[str]:
    pattern = re.compile(a.query if a.regex else re.escape(a.query))
    out: list[str] = []
    for root, dirs, files in os.walk(base):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and (d not in SECRET_DIRS or _FULL_ACCESS.get())]
        for name in files:
            if a.glob and not fnmatch.fnmatch(name, a.glob):
                continue
            path = Path(root) / name
            if is_secret(path):
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
