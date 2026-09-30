"""Undo slots: what the device saves before a mutating tool call so the user can roll that call back later.

A slot is a folder `<root>/<task_id>/<tool_call_id>/` with `manifest.json` and file copies under `files/`. File tools
record the touched paths; shell tools in a git worktree record the tree of the worktree instead.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from mensarium.shared.gitflags import GIT_SAFE_FLAGS
from mensarium.shared.paths import ensure_private_dir
from mensarium.shared.timeutil import now_iso

log = logging.getLogger(__name__)

SLOT_TTL_S = 7 * 24 * 3600
TASK_LIMIT_BYTES = 200 * 1024 * 1024
GIT_TIMEOUT = 60
_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


class UndoError(Exception):
    pass


def _safe(value: str) -> str:
    return _SAFE.sub("_", value).lstrip(".")[:120] or "_"


def _git(cwd: Path, *args: str, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(["git", "--literal-pathspecs", *GIT_SAFE_FLAGS, *args], cwd=cwd, capture_output=True, text=True, timeout=GIT_TIMEOUT, env=env)
    if proc.returncode != 0:
        raise UndoError((proc.stderr or proc.stdout).strip()[:500] or f"git {args[0]} failed")
    return proc.stdout


def _worktree_tree(top: Path) -> str:
    """The tree of everything git would add from this worktree (ignored files left out), via a scratch index."""
    with tempfile.TemporaryDirectory(prefix="mensarium-undo-") as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        _git(top, "add", "-A", "--", ".", env=env)
        return _git(top, "write-tree", env=env).strip()


class UndoSlot:
    def __init__(self, root: Path, task_id: str, tool_call_id: str, tool: str, mode: str) -> None:
        self.path = root / _safe(task_id) / _safe(tool_call_id)
        self.tool, self.mode = tool, mode
        self.entries: list[dict[str, Any]] = []
        self.disabled = False
        self.committed = False

    def _backup(self, path: Path) -> str:
        name = f"files/{len(self.entries)}"
        target = self.path / name
        ensure_private_dir(target.parent)
        shutil.copy2(path, target, follow_symlinks=False)
        return name

    def file(self, path: Path) -> None:
        if path.is_symlink() or path.is_file():
            self.entries.append({"op": "file", "path": str(path), "backup": self._backup(path)})
        elif not path.exists():
            self.entries.append({"op": "file", "path": str(path), "existed": False})
        else:
            self.disabled = True

    def dir(self, path: Path) -> None:
        self.entries.append({"op": "dir", "path": str(path), "existed": path.is_dir()})

    def move(self, src: Path, dst: Path) -> None:
        entry: dict[str, Any] = {"op": "move", "src": str(src), "dst": str(dst)}
        if dst.is_file():
            entry["backup"] = self._backup(dst)
        elif dst.exists():
            self.disabled = True
        self.entries.append(entry)

    def copy(self, src: Path, dst: Path) -> None:
        entry: dict[str, Any] = {"op": "copy", "dst": str(dst)}
        if dst.is_file():
            entry["backup"] = self._backup(dst)
        elif dst.exists():
            self.disabled = True  # a copy merged into an existing folder cannot be taken apart again
        self.entries.append(entry)

    def tree(self, cwd: Path) -> None:
        try:
            top = Path(_git(cwd, "rev-parse", "--show-toplevel").strip())
        except (UndoError, subprocess.SubprocessError):
            self.disabled = True
            return
        self.entries.append({"op": "tree", "cwd": str(top), "tree": _worktree_tree(top), "started": time.time()})

    def after(self) -> None:
        """The tree once the command has run: the rollback touches only what changed between the two."""
        for entry in self.entries:
            if entry["op"] == "tree" and "after" not in entry:
                entry["after"] = _worktree_tree(Path(entry["cwd"]))

    def commit(self) -> bool:
        """Write the manifest; False (and nothing kept) when the call cannot be undone."""
        if self.disabled or not self.entries:
            self.discard()
            return False
        ensure_private_dir(self.path)
        manifest = {"tool": self.tool, "mode": self.mode, "created_at": now_iso(), "entries": self.entries}
        (self.path / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False))
        self.committed = True
        prune(self.path.parent.parent)
        return True

    def discard(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def _restore_file(slot: Path, entry: dict[str, Any]) -> None:
    path = Path(entry["path"])
    if entry.get("backup"):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.is_dir() and not path.is_symlink():
            raise UndoError(f"{path} is a folder now")
        if path.is_symlink() or path.exists():
            path.unlink()
        shutil.copy2(slot / entry["backup"], path, follow_symlinks=False)
    elif path.is_symlink() or path.is_file():
        path.unlink()


def _restore_tree(entry: dict[str, Any]) -> list[str]:
    top, saved, after = Path(entry["cwd"]), str(entry["tree"]), entry.get("after")
    if not after:
        raise UndoError("the command did not finish, so its changes are unknown")
    if after == saved:
        return []
    added: list[str] = []
    changed: list[str] = []
    raw = _git(top, "diff-tree", "-r", "--name-status", "-z", saved, str(after)).split("\0")
    for status, name in zip(raw[::2], raw[1::2], strict=False):
        (added if status.startswith("A") else changed).append(name)
    started = float(entry.get("started") or 0)
    for name in added:
        # Only files the command made: an older file that merely stopped being ignored stays.
        target = top / name
        if (target.is_symlink() or target.is_file()) and target.lstat().st_mtime >= started:
            target.unlink()
    if changed:
        _git(top, "restore", f"--source={saved}", "--worktree", "--", *changed)
    return [str(top / n) for n in added + changed]


def apply_undo(root: Path, task_id: str, tool_call_id: str) -> list[str]:
    """Put back what the tool call changed; the slot is removed once everything is restored."""
    slot = root / _safe(task_id) / _safe(tool_call_id)
    try:
        manifest = json.loads((slot / "manifest.json").read_text())
    except (OSError, ValueError) as e:
        raise UndoError("nothing to roll back: the saved state is gone") from e
    restored: list[str] = []
    for entry in reversed(manifest["entries"]):
        op = entry["op"]
        if op == "file":
            _restore_file(slot, entry)
            restored.append(entry["path"])
        elif op == "dir":
            path = Path(entry["path"])
            if entry["existed"]:
                path.mkdir(parents=True, exist_ok=True)
            elif path.is_dir():
                try:
                    path.rmdir()
                except OSError:
                    pass
            restored.append(entry["path"])
        elif op == "move":
            src, dst = Path(entry["src"]), Path(entry["dst"])
            if dst.exists() or dst.is_symlink():
                src.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(src))
            if entry.get("backup"):
                _restore_file(slot, {"path": entry["dst"], "backup": entry["backup"]})
            restored += [entry["src"], entry["dst"]]
        elif op == "copy":
            dst = Path(entry["dst"])
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            elif dst.exists() or dst.is_symlink():
                dst.unlink()
            if entry.get("backup"):
                _restore_file(slot, {"path": entry["dst"], "backup": entry["backup"]})
            restored.append(entry["dst"])
        elif op == "tree":
            restored += _restore_tree(entry)
    shutil.rmtree(slot, ignore_errors=True)
    return restored


def prune(root: Path) -> None:
    """Drop slots older than a week and the oldest ones of a task past its size limit."""
    try:
        _prune(root)
    except OSError as e:
        log.warning("undo slots not pruned", extra={"error": str(e)})


def _prune(root: Path) -> None:
    if not root.is_dir():
        return
    cutoff = time.time() - SLOT_TTL_S
    for task_dir in root.iterdir():
        if not task_dir.is_dir():
            continue
        slots = []
        for slot in task_dir.iterdir():
            manifest = slot / "manifest.json"
            if not manifest.is_file() or manifest.stat().st_mtime < cutoff:
                shutil.rmtree(slot, ignore_errors=True)
                continue
            size = sum(f.stat().st_size for f in slot.rglob("*") if f.is_file())
            slots.append((manifest.stat().st_mtime, size, slot))
        total = sum(s[1] for s in slots)
        for _, size, slot in sorted(slots):
            if total <= TASK_LIMIT_BYTES:
                break
            shutil.rmtree(slot, ignore_errors=True)
            total -= size
        if not any(task_dir.iterdir()):
            task_dir.rmdir()
