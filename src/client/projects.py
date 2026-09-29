import asyncio
import contextlib
import logging
import os
import re
import shutil
import tempfile
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mensarium.client.tools import GIT_SAFE_FLAGS, SKIP_DIRS, ExecTimeout, Executor, ToolError, _run
from mensarium.contracts.projects import (
    BRANCH_PREFIX,
    BRANCH_RE,
    CHAT_REFS,
    DEVICE_REFS,
    DOC_FILES,
    FOLDER_EXCLUDES,
    INSTRUCTIONS_LIMIT,
    SECRET_EXCLUDES,
    SNAPSHOT_REF,
    BundleInfo,
    ProjectBundle,
    ProjectKind,
    ProjectOp,
    ProjectOpStatus,
    ProjectSnapshot,
    ProjectSnapshotStatus,
)
from mensarium.shared import bundles
from mensarium.shared.bundles import BundleTooLarge
from mensarium.shared.paths import ensure_private_dir, mensarium_home
from mensarium.shared.redaction import SECRET_DIRS, is_secret_path

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Mensarium",
    "GIT_AUTHOR_EMAIL": "agent@mensarium",
    "GIT_COMMITTER_NAME": "Mensarium",
    "GIT_COMMITTER_EMAIL": "agent@mensarium",
    "GIT_TERMINAL_PROMPT": "0",
}
SECRET_GLOBS = [f"**/{pat}" for pat in SECRET_EXCLUDES] + [f"**/{d}/**" for d in SECRET_DIRS]
SECRET_PATHSPECS = [f":(exclude,glob){g}" for g in SECRET_GLOBS]
GIT_TIMEOUT = 600
DIFF_FILES = 2000
PATCH_BYTES = 400_000
SHA_RE = re.compile(r"[0-9a-f]{7,64}")
NO_GIT = "git is not installed on this device"
NO_ACCESS = (
    "no access to the repository: it is private or does not exist. For a private repository use the ssh address "
    "(git@github.com:user/repo.git) with an ssh key set up on this machine, or a credential helper for https"
)
SAFE_ID = re.compile(r"[A-Za-z0-9_-]+")
INCOMING_TTL = 600

log = logging.getLogger(__name__)
Send = Callable[[dict[str, Any]], Awaitable[None]]


def _safe_id(value: str) -> str:
    if not SAFE_ID.fullmatch(value):
        raise ToolError(f"invalid id {value!r}")
    return value


def _branch(value: str) -> str:
    if not value.startswith(BRANCH_PREFIX):
        raise ToolError(f"branch {value!r} is not a {BRANCH_PREFIX} branch")
    return value


def _ref_name(value: str) -> str:
    if not BRANCH_RE.fullmatch(value):
        raise ToolError(f"{value!r} is not a valid branch name")
    return value


class ProjectHost:
    def __init__(self, executor: Executor) -> None:
        self.executor = executor
        self.root = executor.projects_root
        self.git = shutil.which("git")
        self.argv = [self.git or "git", *GIT_SAFE_FLAGS]
        self.locks: dict[str, asyncio.Lock] = {}
        self.inbox = self.root / "inbox"
        shutil.rmtree(self.inbox, ignore_errors=True)
        self.active: set[str] = set()
        self.incoming: dict[str, float] = {}

    @property
    def enabled(self) -> bool:
        return self.git is not None

    # ---- paths ------------------------------------------------------------------

    def _source(self, value: str, project_id: str = "", git_url: str | None = None, exists: bool = True) -> Path:
        src = self.executor._path(value)
        if git_url:
            # A repository given by URL lives in our own clone under the projects root, nowhere else.
            if src != self._clone(project_id):
                raise ToolError("a cloned project must live in its own clone folder")
        else:
            home = mensarium_home().resolve()
            if src == home or src.is_relative_to(home):
                raise ToolError("a project cannot live inside ~/.mensarium")
        if exists and not src.is_dir():
            raise ToolError(f"{value} is not a directory on this device")
        return src

    def _clone(self, project_id: str) -> Path:
        return self.root / _safe_id(project_id) / "src"

    def _shadow(self, project_id: str) -> Path:
        return self.root / _safe_id(project_id) / "shadow.git"

    def _repo(self, project_id: str) -> Path:
        return self.root / _safe_id(project_id) / "repo.git"

    def _worktree(self, project_id: str, task_id: str) -> Path:
        return self.root / _safe_id(project_id) / "wt" / _safe_id(task_id)

    def _lock(self, project_id: str) -> asyncio.Lock:
        return self.locks.setdefault(project_id, asyncio.Lock())

    def _base(self, kind: ProjectKind, project_id: str, role: str = "source") -> list[str]:
        if role == "executor":
            return ["--git-dir", str(self._repo(project_id))]
        return [] if kind == "repo" else ["--git-dir", str(self._shadow(project_id))]

    async def _call(self, *args: str, cwd: Path, env: dict[str, str] | None = None, timeout: float = GIT_TIMEOUT) -> tuple[int, str, str]:
        return await _run([*self.argv, *args], cwd=cwd, timeout=timeout, env={**os.environ, **GIT_ENV, **(env or {})})

    async def _git(self, *args: str, cwd: Path, env: dict[str, str] | None = None, check: bool = True) -> str:
        code, out, err = await self._call(*args, cwd=cwd, env=env)
        if check and code != 0:
            raise ToolError((err or out).strip()[:2000] or f"git {args[0]} failed with code {code}")
        return out

    async def _rev(self, base: list[str], ref: str, cwd: Path) -> str | None:
        code, out, _ = await self._call(*base, "rev-parse", "--verify", "--quiet", ref, cwd=cwd, timeout=60)
        return out.strip() or None if code == 0 else None

    # ---- shadow repo (folder kind) -------------------------------------------------

    async def _ensure_shadow(self, project_id: str, src: Path) -> None:
        shadow = self._shadow(project_id)
        if shadow.exists():
            return
        ensure_private_dir(shadow.parent)
        await self._git("init", "--bare", "--quiet", str(shadow), cwd=src)
        await self._git("--git-dir", str(shadow), "config", "core.bare", "false", cwd=src)
        await self._git("--git-dir", str(shadow), "config", "core.bigFileThreshold", "1m", cwd=src)
        await self._git("--git-dir", str(shadow), "config", "core.excludesFile", str(src / ".mensariumignore"), cwd=src)
        lines = [*sorted(SKIP_DIRS), *FOLDER_EXCLUDES, *SECRET_EXCLUDES, *(f"{d}/" for d in SECRET_DIRS)]
        (shadow / "info").mkdir(exist_ok=True)
        (shadow / "info" / "exclude").write_text("\n".join(lines) + "\n")

    # A device that runs chats of a project it is not the source of keeps the Core's history in a bare repo.git.
    async def _ensure_repo(self, project_id: str) -> Path:
        bare = self._repo(project_id)
        if not (bare / "HEAD").is_file():
            ensure_private_dir(bare.parent)
            await self._git("init", "--bare", "--quiet", str(bare), cwd=self.root)
        return bare

    # ---- snapshot ---------------------------------------------------------------

    async def snapshot(self, req: ProjectSnapshot, send: Send | None = None) -> ProjectSnapshotStatus:
        status = ProjectSnapshotStatus(request_id=req.request_id, project_id=req.project_id, state="error")
        if not self.enabled:
            status.detail = NO_GIT
            return status
        self.active.add(req.request_id)
        try:
            async with self._lock(req.project_id):
                result = await self._snapshot(req.project_id, req.source_path, req.kind, req.include_remotes, req.fetch_origin, req.size_limit_mb, req.file_limit_mb, req.git_url)
                status = status.model_copy(update=result)
                status.state = "unchanged" if status.refs == req.known else "ok"
                if status.state == "ok" and req.bundle and send is not None:
                    src = self._source(req.source_path, req.project_id, req.git_url, exists=not req.git_url)
                    moved = {ref: sha for ref, sha in status.refs.items() if req.known.get(ref) != sha}
                    base = self._base(status.kind or "repo", req.project_id)
                    status.bundle = await self._bundle_up(base, src, moved, req.known, req.project_id, req.request_id, send)
        except (ToolError, ExecTimeout, OSError) as e:
            return ProjectSnapshotStatus(request_id=req.request_id, project_id=req.project_id, state="error", detail=str(e))
        finally:
            self._done(req.request_id)
        return status

    async def _snapshot(
        self, project_id: str, source_path: str, kind: ProjectKind | None, include_remotes: bool, fetch_origin: bool, size_limit_mb: int, file_limit_mb: int, git_url: str | None = None
    ) -> dict[str, Any]:
        src = self._source(source_path, project_id, git_url, exists=not git_url)
        if git_url:
            kind = "repo"
            if not (src / ".git").exists():
                await self._clone_repo(git_url, src)
            elif fetch_origin:
                # The clone is ours alone, so its checkout may follow origin; a chat branch never lives here.
                await self._git("pull", "--ff-only", "--quiet", cwd=src)
        kind = kind or ("repo" if (src / ".git").exists() else "folder")
        base = self._base(kind, project_id)
        if kind == "folder":
            await self._ensure_shadow(project_id, src)
        elif fetch_origin and not git_url:
            await self._git("fetch", "--all", "--prune", "--quiet", cwd=src, check=False)
        head = await self._rev(base, "HEAD", src)
        previous = await self._rev(base, SNAPSHOT_REF, src)
        parent = head if kind == "repo" else previous

        listing = await self._git(*base, "ls-files", "-z", "--cached", "--others", "--exclude-standard", cwd=src)
        excludes = list(SECRET_PATHSPECS)
        skipped: list[str] = []
        total = 0
        file_limit = file_limit_mb * 1024 * 1024
        for rel in filter(None, listing.split("\0")):
            try:
                size = (src / rel).lstat().st_size
            except OSError:
                continue
            if size > file_limit:
                skipped.append(rel)
                excludes.append(f":(exclude,literal){rel}")
            else:
                total += size
        if total > size_limit_mb * 1024 * 1024:
            raise ToolError(f"the project is {total // 1_048_576} MB, above the {size_limit_mb} MB limit; raise the limit or exclude folders with .mensariumignore")

        with tempfile.TemporaryDirectory(prefix="mensarium-index-") as tmp:
            env = {"GIT_INDEX_FILE": str(Path(tmp) / "index")}
            if parent:
                await self._git(*base, "read-tree", parent, cwd=src, env=env)
            await self._git(*base, "add", "-A", "--", ".", *excludes, cwd=src, env=env)
            tree = (await self._git(*base, "write-tree", cwd=src, env=env)).strip()
        parent_tree = (await self._git(*base, "rev-parse", f"{parent}^{{tree}}", cwd=src)).strip() if parent else None
        if parent and tree == parent_tree:
            snapshot = parent
        elif previous and previous != parent and await self._rev(base, f"{previous}^{{tree}}", src) == tree and await self._rev(base, f"{previous}^", src) == parent:
            snapshot = previous
        else:
            args = [*base, "commit-tree", tree, "-m", "mensarium: device working state"] + (["-p", parent] if parent else [])
            snapshot = (await self._git(*args, cwd=src)).strip()
        await self._git(*base, "update-ref", SNAPSHOT_REF, snapshot, cwd=src)

        patterns = ["refs/heads"] + (["refs/remotes"] if kind == "repo" and include_remotes else [])
        refs: dict[str, str] = {SNAPSHOT_REF: snapshot}
        if kind == "repo":
            out = await self._git(*base, "for-each-ref", "--format=%(refname) %(objectname)", *patterns, cwd=src)
            for line in out.splitlines():
                name, _, sha = line.partition(" ")
                if name and sha:
                    refs[name] = sha
        branch = None
        if kind == "repo":
            code, out, _ = await self._call("symbolic-ref", "--short", "--quiet", "HEAD", cwd=src, timeout=30)
            branch = out.strip() or None if code == 0 else None
        main = await self._default_base(src) if kind == "repo" else None
        return {"kind": kind, "head_sha": head, "snapshot_sha": snapshot, "branch": branch, "main": main, "refs": refs, "size_bytes": total, "skipped": skipped}

    # Sends `refs` as a git bundle in project.bundle frames, cut at the commits the Core already has (`known`).
    async def _bundle_up(self, base: list[str], cwd: Path, refs: dict[str, str], known: dict[str, str], project_id: str, request_id: str, send: Send) -> BundleInfo | None:
        if not refs:
            return None
        ensure_private_dir(self.inbox)
        path = self.inbox / f"{_safe_id(request_id)}.up.bundle"
        try:
            path.unlink(missing_ok=True)
            have: list[str] = []
            for sha in sorted({known[ref] for ref in refs if known.get(ref)}):
                if SHA_RE.fullmatch(sha) and await self._rev(base, f"{sha}^{{commit}}", cwd):
                    have.append(sha)
            revs = [*refs, *(f"^{sha}" for sha in have)]
            if int((await self._git(*base, "rev-list", "--count", *revs, cwd=cwd)).strip() or 0) == 0:
                return None
            await self._git(*base, "bundle", "create", "--quiet", str(path), *revs, cwd=cwd)
            for seq, data in enumerate(bundles.chunks(path)):
                await send(ProjectBundle(request_id=request_id, project_id=project_id, seq=seq, data=data).model_dump())
            return bundles.describe(path, refs, have)
        finally:
            path.unlink(missing_ok=True)

    def _done(self, request_id: str) -> None:
        self.active.discard(request_id)
        if SAFE_ID.fullmatch(request_id):
            (self.inbox / f"{request_id}.bundle").unlink(missing_ok=True)

    # A project.bundle frame for a request being handled now, or one whose signed op has not arrived yet (a fetch).
    def receive_chunk(self, msg: dict[str, Any]) -> None:
        now = time.monotonic()
        for rid in [rid for rid, until in self.incoming.items() if until < now]:
            del self.incoming[rid]
            (self.inbox / f"{rid}.bundle").unlink(missing_ok=True)
        try:
            chunk = ProjectBundle.model_validate(msg)
        except ValidationError:
            return
        if not SAFE_ID.fullmatch(chunk.request_id):
            return
        if chunk.request_id not in self.active:
            self.incoming.setdefault(chunk.request_id, now + INCOMING_TTL)
        try:
            bundles.append_chunk(self.inbox / f"{_safe_id(chunk.request_id)}.bundle", chunk.data)
        except (BundleTooLarge, ToolError, ValueError, OSError) as e:
            log.warning("bundle chunk dropped", extra={"request_id": chunk.request_id, "error": str(e)})

    async def _clone_repo(self, git_url: str, dst: Path) -> None:
        ensure_private_dir(dst.parent)
        shutil.rmtree(dst, ignore_errors=True)
        code, out, err = await self._call("clone", "--quiet", "--", git_url, str(dst), cwd=dst.parent)
        if code != 0:
            shutil.rmtree(dst, ignore_errors=True)
            text = (err or out).strip()
            if "could not read Username" in text or "Authentication failed" in text or "Permission denied" in text:
                raise ToolError(NO_ACCESS)
            raise ToolError(text.splitlines()[-1][:500] if text else f"git clone failed with code {code}")

    # ---- ops --------------------------------------------------------------------

    async def op(self, req: ProjectOp, send: Send | None = None) -> ProjectOpStatus:
        status = ProjectOpStatus(request_id=req.request_id, project_id=req.project_id, task_id=req.task_id, op=req.op, state="error")
        if not self.enabled:
            status.detail = NO_GIT
            return status
        handler = {
            "browse": self._browse, "checkout": self._checkout, "commit": self._commit, "status": self._status, "remove": self._remove,
            "branches": self._branches, "diff": self._diff, "docs": self._docs, "revert": self._revert, "fetch": self._fetch,
        }[req.op]
        lock = contextlib.nullcontext() if req.op in ("browse", "branches", "diff", "docs") else self._lock(req.project_id)
        self.incoming.pop(req.request_id, None)
        self.active.add(req.request_id)
        try:
            async with lock:
                result = await handler(req.project_id, req.task_id, req.args, send, req.request_id)
        except (ToolError, ExecTimeout, OSError, KeyError, TypeError, ValueError) as e:
            status.detail = str(e) if not isinstance(e, KeyError) else f"missing argument {e}"
            return status
        finally:
            self._done(req.request_id)
        return status.model_copy(update={"state": "ok", **result})

    async def _browse(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        path = self.executor._path(str(a.get("path") or "~"))
        if not path.is_dir():
            raise ToolError(f"{path} is not a directory")
        entries = []
        with os.scandir(path) as it:
            for entry in sorted(it, key=lambda e: e.name.lower()):
                if entry.name.startswith(".") or not entry.is_dir(follow_symlinks=False):
                    continue
                entries.append({"name": entry.name, "path": str(path / entry.name), "git": (path / entry.name / ".git").exists()})
        parent = str(path.parent) if path != path.parent else None
        try:
            self.executor._path(parent or path.as_posix())
        except ToolError:
            parent = None
        return {"data": {"path": str(path), "parent": parent, "git": (path / ".git").exists(), "entries": entries}}

    async def _current(self, cwd: Path) -> str | None:
        code, out, _ = await self._call("symbolic-ref", "--short", "--quiet", "HEAD", cwd=cwd, timeout=30)
        return out.strip() or None if code == 0 else None

    # The project's main branch: origin's HEAD, main or master; a local branch wins over its remote copy.
    async def _default_base(self, src: Path) -> str:
        code, out, _ = await self._call("symbolic-ref", "--short", "--quiet", "refs/remotes/origin/HEAD", cwd=src, timeout=30)
        remote = out.strip() if code == 0 else ""
        names = [remote.split("/", 1)[1]] if "/" in remote else []
        for name in dict.fromkeys([*names, "main", "master"]):
            if await self._rev([], f"refs/heads/{name}", src):
                return name
        for name in dict.fromkeys([remote, "origin/main", "origin/master"]):
            if name and await self._rev([], f"refs/remotes/{name}", src):
                return name
        return await self._current(src) or "HEAD"

    async def _branches(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        src = self._source(str(a["source_path"]), project_id, a.get("git_url"))
        if a["kind"] != "repo":
            return {"data": {"branches": [], "default": None, "current": None}}
        fmt = "--format=%(refname)%00%(committerdate:unix)"
        out = await self._git("for-each-ref", "--sort=-committerdate", "--count=500", fmt, "refs/heads", "refs/remotes", cwd=src)
        items = []
        for line in out.splitlines():
            ref, _, ts = line.partition("\0")
            if ref.endswith("/HEAD"):
                continue
            remote = ref.startswith("refs/remotes/")
            name = ref.removeprefix("refs/remotes/" if remote else "refs/heads/")
            items.append({"name": name, "remote": remote, "updated": int(ts) if ts.isdigit() else None})
        return {"data": {"branches": items, "default": await self._default_base(src), "current": await self._current(src)}}

    async def _checkout(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        executor = str(a.get("role") or "source") == "executor"
        kind: ProjectKind = "repo" if executor else a["kind"]
        if executor:
            await self._ensure_repo(project_id)
            cwd = self.root
        else:
            cwd = self._source(str(a["source_path"]), project_id, a.get("git_url"))
        base = self._base(kind, project_id, "executor" if executor else "source")
        branch = _ref_name(str(a["branch"]))
        code, _, _ = await self._call("check-ref-format", "--branch", branch, cwd=cwd, timeout=30)
        if code != 0:
            raise ToolError(f"{branch!r} is not a valid branch name")
        wt = self._worktree(project_id, task_id)
        if wt.exists():
            code, out, _ = await self._call("symbolic-ref", "--short", "--quiet", "HEAD", cwd=wt, timeout=30)
            if code != 0 or out.strip() != branch:
                raise ToolError("the worktree for this chat exists on another branch")
            return {"head_sha": (await self._git("rev-parse", "HEAD", cwd=wt)).strip()}
        start = str(a["start"])
        base_name = start
        if executor:
            if not SHA_RE.fullmatch(start) or not await self._rev(base, f"{start}^{{commit}}", cwd):
                raise ToolError("the start commit is missing on this device")
            base_name = str(a.get("base_name") or start[:10])
        elif start == "snapshot":
            snap = await self._snapshot(project_id, str(a["source_path"]), kind, bool(a.get("include_remotes", True)), False, int(a.get("size_limit_mb", 1024)), int(a.get("file_limit_mb", 100)), a.get("git_url"))
            start = str(snap["snapshot_sha"])
        elif kind == "repo":
            base_name = await self._default_base(cwd) if start == "default" else _ref_name(start)
            sha = await self._rev(base, f"{base_name}^{{commit}}", cwd)
            if not sha:
                raise ToolError(f"branch {base_name} is not found on this device")
            start = sha
        else:
            raise ToolError("a folder project starts only from its snapshot")
        ensure_private_dir(wt.parent.parent)
        ensure_private_dir(wt.parent)
        await self._git(*base, "worktree", "prune", cwd=cwd)
        if await self._rev(base, f"refs/heads/{branch}", cwd):
            raise ToolError(f"branch {branch} already exists on this device")
        await self._git(*base, "worktree", "add", "--quiet", "--no-track", "-B", branch, str(wt), start, cwd=cwd)
        return {"head_sha": start, "data": {"base": base_name}}

    # Takes refs from a Core bundle: into repo.git on an executor, into the user's repository (or shadow.git) on the source.
    async def _fetch(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        info = BundleInfo.model_validate(a["bundle"])
        refs = {str(k): str(v) for k, v in dict(a["refs"]).items()}
        for dst in refs.values():
            if not dst.startswith((CHAT_REFS, DEVICE_REFS)) or not BRANCH_RE.fullmatch(dst.removeprefix("refs/")):
                raise ToolError(f"{dst} is not a ref this device takes from the Core")
        if str(a.get("role") or "source") == "executor":
            cwd, base = self.root, ["--git-dir", str(await self._ensure_repo(project_id))]
        else:
            kind: ProjectKind = a["kind"]
            cwd = self._source(str(a["source_path"]), project_id, a.get("git_url"))
            base = self._base(kind, project_id)
            busy = await self._git(*base, "worktree", "list", "--porcelain", cwd=cwd, check=False)
            taken = {line.split(" ", 1)[1] for line in busy.splitlines() if line.startswith("branch ")}
            if held := [dst for dst in refs.values() if dst in taken]:
                raise ToolError(f"{held[0].removeprefix('refs/heads/')} is checked out in a worktree on this device")
        if missing := [src for src in refs if src not in info.refs]:
            raise ToolError(f"{missing[0]} is not in the bundle")
        path = self.inbox / f"{_safe_id(request_id)}.bundle"
        try:
            bundles.check(path, info)
        except ValueError as e:
            raise ToolError(str(e)) from e
        await self._git(*base, "bundle", "verify", "--quiet", str(path), cwd=cwd)
        await self._git(*base, "fetch", "--quiet", "--no-tags", str(path), *(f"+{src}:{dst}" for src, dst in refs.items()), cwd=cwd)
        return {"data": {"refs": {dst: info.refs[src] for src, dst in refs.items()}}}

    async def _commit(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        wt = self._worktree(project_id, task_id)
        if not wt.is_dir():
            raise ToolError("the worktree for this chat is missing on this device")
        before = (await self._git("rev-parse", "HEAD", cwd=wt)).strip()
        await self._git("add", "-A", "--", ".", *SECRET_PATHSPECS, cwd=wt)
        await self._git("reset", "-q", "HEAD", "--", *(f":(glob){g}" for g in SECRET_GLOBS), cwd=wt)
        code, _, _ = await self._call("diff", "--cached", "--quiet", cwd=wt, timeout=120)
        if code != 0:
            await self._git("commit", "--quiet", "--no-verify", "-m", str(a.get("message") or "mensarium: agent turn"), cwd=wt)
        head = (await self._git("rev-parse", "HEAD", cwd=wt)).strip()
        changed = 0
        if head != before:
            names = await self._git("diff", "--name-only", before, head, cwd=wt)
            changed = len([n for n in names.splitlines() if n.strip()])
        result: dict[str, Any] = {"head_sha": head, "changed": changed, "bundle": None}
        branch = str(a.get("branch") or "")
        if send is not None and branch and head != a.get("known_head"):
            # The turn is already committed: a failed upload must not hide the new head from the Core.
            try:
                ref = f"refs/heads/{_ref_name(branch)}"
                known = str(a.get("known_head") or a.get("base_sha") or "")
                result["bundle"] = await self._bundle_up([], wt, {ref: head}, {ref: known} if known else {}, project_id, request_id, send)
            except (ToolError, ExecTimeout, OSError) as e:
                result["detail"] = f"bundle not sent: {e}"
        base = str(a.get("base_sha") or "")
        if not SHA_RE.fullmatch(base):
            return result
        rows = [r.split("\t", 2) for r in (await self._git("diff", "--numstat", "-z", "--no-renames", base, head, cwd=wt)).split("\0") if r]
        stat = {"files": len(rows), "added": sum(int(r[0]) for r in rows if r[0].isdigit()), "deleted": sum(int(r[1]) for r in rows if r[1].isdigit())}
        return {**result, "data": {"stat": stat}}

    async def _status(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        wt = self._worktree(project_id, task_id)
        if not wt.is_dir():
            raise ToolError("the worktree for this chat is missing on this device")
        out = await self._git("status", "--porcelain=v2", "--branch", cwd=wt)
        head = (await self._git("rev-parse", "HEAD", cwd=wt)).strip()
        return {"head_sha": head, "detail": out[:8000]}

    async def _docs(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        src = self._source(str(a["source_path"]), project_id, a.get("git_url"))
        files = []
        for name in DOC_FILES:
            path = src / name
            if path.is_symlink() or not path.is_file():
                continue
            text = path.read_bytes()[: INSTRUCTIONS_LIMIT * 4].decode(errors="replace")
            files.append({"name": name, "size": path.stat().st_size, "text": text[:INSTRUCTIONS_LIMIT], "truncated": len(text) > INSTRUCTIONS_LIMIT})
        return {"data": {"files": files}}

    # The chat's changes since its start, uncommitted ones included; a copy of the index keeps the worktree untouched.
    async def _diff(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        wt = self._worktree(project_id, task_id)
        if not wt.is_dir():
            raise ToolError("the worktree for this chat is missing on this device")
        base = str(a["base_sha"])
        if not SHA_RE.fullmatch(base):
            raise ToolError("invalid base commit")
        with tempfile.TemporaryDirectory(prefix="mensarium-index-") as tmp:
            index = Path(tmp) / "index"
            real = wt / (await self._git("rev-parse", "--git-path", "index", cwd=wt)).strip()
            if real.is_file():
                shutil.copyfile(real, index)
            env = {"GIT_INDEX_FILE": str(index)}
            await self._git("add", "-A", "--", ".", *SECRET_PATHSPECS, cwd=wt, env=env)
            diff = ("diff", "--cached", "--no-color", "--no-ext-diff", "--no-renames", base)
            if a.get("path"):
                path = str(a["path"])
                patch = await self._git(*diff, "--", f":(literal){path}", cwd=wt, env=env)
                return {"data": {"path": path, "patch": patch[:PATCH_BYTES], "truncated": len(patch) > PATCH_BYTES}}
            numstat = (await self._git(*diff, "--numstat", "-z", cwd=wt, env=env)).split("\0")
            names = (await self._git(*diff, "--name-status", "-z", cwd=wt, env=env)).split("\0")
        kinds = dict(zip(names[1::2], names[0::2], strict=False))
        files = []
        for rec in filter(None, numstat):
            added, deleted, path = rec.split("\t", 2)
            binary = added == "-"
            files.append({"path": path, "status": kinds.get(path, "M")[:1], "added": 0 if binary else int(added), "deleted": 0 if binary else int(deleted), "binary": binary})
        return {"changed": len(files), "data": {"files": files[:DIFF_FILES], "truncated": len(files) > DIFF_FILES}}

    # Puts one file back to the chat's start: an added file goes away, a changed or deleted one comes back.
    async def _revert(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        wt = self._worktree(project_id, task_id)
        if not wt.is_dir():
            raise ToolError("the worktree for this chat is missing on this device")
        base, path = str(a["base_sha"]), str(a["path"])
        if not SHA_RE.fullmatch(base):
            raise ToolError("invalid base commit")
        if is_secret_path(path):
            raise ToolError("secret files are not reverted from here")
        spec = f":(literal){path}"
        await self._git("add", "-A", "--", spec, cwd=wt)
        await self._git("restore", f"--source={base}", "--staged", "--worktree", "--", spec, cwd=wt)
        return {"head_sha": (await self._git("rev-parse", "HEAD", cwd=wt)).strip()}

    async def _remove(self, project_id: str, task_id: str, a: dict[str, Any], send: Send | None, request_id: str) -> dict[str, Any]:
        executor = str(a.get("role") or "source") == "executor"
        kind: ProjectKind = "repo" if executor else a["kind"]
        base = self._base(kind, project_id, "executor" if executor else "source")
        project_dir = self.root / _safe_id(project_id)
        wt = self._worktree(project_id, task_id) if task_id else None
        branch = _branch(str(a["branch"])) if wt and a.get("delete_branch") and a.get("branch") else None
        cwd: Path | None
        if executor:
            cwd = self.root if (self._repo(project_id) / "HEAD").is_file() else None
        else:
            try:
                cwd = self._source(str(a["source_path"]), project_id, a.get("git_url"))
            except ToolError:
                cwd = self.root if kind == "folder" else None
        if wt and wt.exists():
            if cwd:
                await self._git(*base, "worktree", "remove", "--force", str(wt), cwd=cwd, check=False)
            shutil.rmtree(wt, ignore_errors=True)
        if cwd:
            await self._git(*base, "worktree", "prune", cwd=cwd, check=False)
            if branch:
                await self._git(*base, "branch", "-D", branch, cwd=cwd, check=False)
        if cwd and not task_id and kind == "repo" and not executor:
            await self._git("update-ref", "-d", SNAPSHOT_REF, cwd=cwd, check=False)
        if a.get("delete_repo") and executor:
            shutil.rmtree(self._repo(project_id), ignore_errors=True)
        if a.get("delete_shadow") and kind == "folder":
            shutil.rmtree(self._shadow(project_id), ignore_errors=True)
        if a.get("delete_clone") and a.get("git_url") and not task_id:
            shutil.rmtree(self._clone(project_id), ignore_errors=True)
        for d in (project_dir / "wt", project_dir):
            if d.exists() and not any(d.iterdir()):
                d.rmdir()
        return {}
