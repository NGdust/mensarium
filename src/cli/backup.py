"""Portable Core bundles (.pab): the Core's data and, on request, the built-in device's folders and project copies."""

import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import IO, Any

import yaml
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from mensarium import __version__
from mensarium.core.config import CoreConfig, CorePaths
from mensarium.core.device import device_roots
from mensarium.shared.paths import ensure_private_dir, mensarium_home, projects_dir
from mensarium.shared.timeutil import now_iso

MAGIC_V1 = b"PAB1"
MAGIC = b"PAB2"
CHUNK = 1 << 20
REQUIRED = ("config.yaml", "secrets", "keys", "device", "skills", "instructions")
OPTIONAL = {"artifacts": "Attachments and tool results", "logs": "Core logs"}
# Rebuilt by a package manager or a build; never the only copy of anything.
REBUILDABLE = frozenset({
    "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".ruff_cache", ".pytest_cache", ".tox",
    ".next", ".nuxt", ".gradle", "dist", "build", "target",
})  # fmt: skip


class BackupError(Exception):
    pass


@dataclass
class Item:
    key: str
    title: str
    path: Path
    size: int = 0
    skipped: int = 0
    default: bool = True


@dataclass
class Restored:
    manifest: dict[str, Any]
    previous: Path | None
    warnings: list[str]


def human(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _key(passphrase: str, salt: bytes) -> bytes:
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode())


# ---- what goes in ---------------------------------------------------------------


def _measure(path: Path, excluded: set[Path], skip_rebuildable: bool) -> tuple[int, int]:
    if path.is_file():
        return path.stat().st_size, 0
    size = skipped = 0
    stack = [(path, False)]
    while stack:
        current, rebuild = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    if Path(e.path) not in excluded:
                        stack.append((Path(e.path), rebuild or (skip_rebuildable and e.name in REBUILDABLE)))
                elif e.is_file(follow_symlinks=False):
                    n = e.stat(follow_symlinks=False).st_size
                    skipped, size = (skipped + n, size) if rebuild else (skipped, size + n)
            except OSError:
                continue
    return size, skipped


def _outermost(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for p in sorted(set(paths), key=lambda x: len(x.parts)):
        if not any(p.is_relative_to(q) for q in out):
            out.append(p)
    return out


def backup_items(paths: CorePaths, cfg: CoreConfig) -> tuple[Item, list[Item]]:
    """The part that always goes in, and the choices with their sizes (rebuildable folders counted apart)."""
    core = Item("core", "database, config, secrets, keys, built-in device, instructions, skills", paths.root)
    core.size = sum(_measure(p, set(), False)[0] for p in [paths.db, *(paths.root / n for n in REQUIRED)] if p.exists())
    items: list[Item] = []
    for name, title in OPTIONAL.items():
        if (paths.root / name).exists():
            items.append(Item(name, title, paths.root / name, default=name != "logs"))
    if projects_dir().exists() and any(projects_dir().iterdir()):
        items.append(Item("projects", "Project copies and history of chats on this machine", projects_dir()))
    if cfg.device.enabled:
        for n, root in enumerate(_outermost([Path(r) for r in device_roots(cfg)])):
            items.append(Item(f"root:{n}", str(root), root))
    excluded = {mensarium_home().resolve()}
    for item in items:
        rebuildable = item.key == "projects" or item.key.startswith("root:")
        item.size, item.skipped = _measure(item.path, excluded, rebuildable)
    return core, items


# ---- sealed stream: AES-GCM chunks, each nonce carries its number and the last-chunk flag ----


class _SealedWriter(io.RawIOBase):
    def __init__(self, out: IO[bytes], key: bytes, prefix: bytes) -> None:
        self.out, self.aead, self.prefix = out, AESGCM(key), prefix
        self.buf = bytearray()
        self.counter = 0

    def writable(self) -> bool:
        return True

    def write(self, b: Any) -> int:
        self.buf += b
        while len(self.buf) > CHUNK:
            self._seal(bytes(self.buf[:CHUNK]), final=False)
            del self.buf[:CHUNK]
        return len(b)

    def finish(self) -> None:
        self._seal(bytes(self.buf), final=True)
        self.buf.clear()

    def _seal(self, data: bytes, final: bool) -> None:
        flag = b"\x01" if final else b"\x00"
        sealed = self.aead.encrypt(self.prefix + self.counter.to_bytes(4, "big") + flag, data, MAGIC)
        self.out.write(flag + len(sealed).to_bytes(4, "big") + sealed)
        self.counter += 1


class _SealedReader(io.RawIOBase):
    def __init__(self, src: IO[bytes], key: bytes, prefix: bytes) -> None:
        self.src, self.aead, self.prefix = src, AESGCM(key), prefix
        self.buf = b""
        self.pos = 0
        self.counter = 0
        self.done = False

    def readable(self) -> bool:
        return True

    def readinto(self, b: Any) -> int:
        while self.pos >= len(self.buf) and not self.done:
            self._open_next()
        n = min(len(b), len(self.buf) - self.pos)
        b[:n] = self.buf[self.pos : self.pos + n]
        self.pos += n
        return n

    def _open_next(self) -> None:
        head = self.src.read(5)
        flag, size = head[:1], int.from_bytes(head[1:5], "big")
        sealed = self.src.read(size) if len(head) == 5 else b""
        if flag not in (b"\x00", b"\x01") or len(sealed) != size or len(head) < 5:
            raise BackupError("the bundle is truncated or corrupted")
        try:
            self.buf = self.aead.decrypt(self.prefix + self.counter.to_bytes(4, "big") + flag, sealed, MAGIC)
        except InvalidTag as e:
            raise BackupError("wrong passphrase or corrupted bundle") from e
        self.pos, self.counter, self.done = 0, self.counter + 1, flag == b"\x01"
        if self.done and self.src.read(1):
            raise BackupError("unexpected data after the end of the bundle")


# ---- export ---------------------------------------------------------------------


def _add_bytes(tar: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size, info.mtime, info.mode = len(data), int(time.time()), 0o600
    tar.addfile(info, io.BytesIO(data))


def _add_tree(tar: tarfile.TarFile, src: Path, arc: str, excluded: set[Path], skip_rebuildable: bool, problems: list[str]) -> None:
    tar.inodes.clear()  # type: ignore[attr-defined]  # hard links go in as plain files: members are renamed on restore
    try:
        info = tar.gettarinfo(str(src), arc)
    except OSError as e:
        problems.append(f"{src}: {e.strerror}")
        return
    if info is None:  # sockets and devices
        return
    if info.isdir():
        if src in excluded or (skip_rebuildable and src.name in REBUILDABLE):
            return
        tar.addfile(info)
        try:
            names = sorted(os.listdir(src))
        except OSError as e:
            problems.append(f"{src}: {e.strerror}")
            return
        for name in names:
            _add_tree(tar, src / name, f"{arc}/{name}", excluded, skip_rebuildable, problems)
    elif info.isreg():
        try:
            with src.open("rb") as f:
                tar.addfile(info, f)
        except OSError as e:
            problems.append(f"{src}: {e.strerror}")
    else:
        tar.addfile(info)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(CHUNK):
            h.update(block)
    return "sha256:" + h.hexdigest()


def export_bundle(paths: CorePaths, out: Path, passphrase: str, items: list[Item], moved_to: str | None = None) -> dict[str, Any]:
    if not paths.config.exists():
        raise BackupError("core is not configured on this host")
    chosen = {i.key for i in items}
    roots = [i for i in items if i.key.startswith("root:")]
    manifest = {
        "format_version": 2,
        "core_version": __version__,
        "created_at": now_iso(),
        "home": str(Path.home().resolve()),
        "mensarium_home": str(mensarium_home()),
        "moved_to": moved_to,
        "items": sorted(chosen),
        "roots": [{"id": n, "path": str(i.path)} for n, i in enumerate(roots)],
        "encryption": {"algorithm": "scrypt+aes-256-gcm", "chunk": CHUNK},
    }
    problems: list[str] = []
    salt, prefix = os.urandom(16), os.urandom(7)
    part = out.with_name(out.name + ".part")
    try:
        with tempfile.TemporaryDirectory() as tmp, part.open("wb") as f:
            part.chmod(0o600)
            f.write(MAGIC + salt + prefix)
            sink = _SealedWriter(f, _key(passphrase, salt), prefix)
            with tarfile.open(fileobj=sink, mode="w|gz") as tar:
                _add_bytes(tar, "manifest.json", json.dumps(manifest, indent=2).encode())
                if paths.db.exists():
                    db_copy = Path(tmp) / "mensarium.db"
                    src, dst = sqlite3.connect(paths.db), sqlite3.connect(db_copy)
                    with dst:
                        src.backup(dst)
                    src.close()
                    dst.close()
                    tar.add(db_copy, arcname="core/mensarium.db")
                for name in (*REQUIRED, *(k for k in OPTIONAL if k in chosen)):
                    if (paths.root / name).exists():
                        _add_tree(tar, paths.root / name, f"core/{name}", set(), False, problems)
                if "projects" in chosen and projects_dir().exists():
                    _add_tree(tar, projects_dir(), "projects", set(), True, problems)
                excluded = {mensarium_home().resolve()}
                for n, item in enumerate(roots):
                    _add_tree(tar, item.path, f"roots/{n}", excluded, True, problems)
            sink.finish()
        part.replace(out)
    finally:
        part.unlink(missing_ok=True)
    return {"file": str(out), "size": out.stat().st_size, "sha256": _sha256(out), "items": sorted(chosen), "problems": problems}


# ---- restore --------------------------------------------------------------------


def _open(f: IO[bytes], passphrase: str) -> tarfile.TarFile:
    magic = f.read(4)
    if magic == MAGIC:
        salt, prefix = f.read(16), f.read(7)
        return tarfile.open(fileobj=_SealedReader(f, _key(passphrase, salt), prefix), mode="r|gz")
    if magic == MAGIC_V1:
        salt, nonce = f.read(16), f.read(12)
        try:
            plain = AESGCM(_key(passphrase, salt)).decrypt(nonce, f.read(), MAGIC_V1)
        except InvalidTag as e:
            raise BackupError("wrong passphrase or corrupted bundle") from e
        return tarfile.open(fileobj=io.BytesIO(plain), mode="r:gz")
    raise BackupError("not a Mensarium .pab bundle")


def _manifest(tar: tarfile.TarFile) -> dict[str, Any]:
    first = tar.next()
    data = tar.extractfile(first) if first and first.name == "manifest.json" else None
    if data is None:
        raise BackupError("the bundle has no manifest")
    manifest: dict[str, Any] = json.loads(data.read())
    return manifest


def read_manifest(bundle: Path, passphrase: str) -> dict[str, Any]:
    with bundle.open("rb") as f, _open(f, passphrase) as tar:
        return _manifest(tar)


def remap(path: str, moves: list[tuple[str, str]]) -> str:
    """Rewrite a path by the most specific move (old prefix -> new prefix) that contains it."""
    p = PurePath(path)
    for old, new in sorted(moves, key=lambda m: len(PurePath(m[0]).parts), reverse=True):
        if p.is_relative_to(old):
            return str(PurePath(new) / p.relative_to(old))
    return path


def planned_roots(manifest: dict[str, Any]) -> dict[int, Path]:
    """Where each device folder goes by default: under the new home when it lived under the old one."""
    moves = [(manifest.get("home") or str(Path.home()), str(Path.home()))]
    return {int(r["id"]): Path(remap(r["path"], moves)) for r in manifest.get("roots", [])}


def can_write(path: Path) -> bool:
    while not path.exists():
        path = path.parent
    return os.access(path, os.W_OK)


def _aside(path: Path) -> Path | None:
    if not path.exists() or not any(path.iterdir()):
        return None
    previous = path.with_name(f"{path.name}.before-restore-{now_iso().replace(':', '')}")
    shutil.move(path, previous)
    return previous


def _extract_filter(member: tarfile.TarInfo, dest: str) -> tarfile.TarInfo:
    # Keep links and modes as they were, but never write outside the destination or chown to the old host's users.
    return tarfile.tar_filter(member, dest).replace(uid=None, gid=None, uname=None, gname=None, deep=False)  # type: ignore[arg-type]


def import_bundle(paths: CorePaths, bundle: Path, passphrase: str, roots: dict[int, Path] | None = None) -> Restored:
    """Unpack a bundle; folders of the built-in device go where `roots` says, paths in the Core follow them."""
    with bundle.open("rb") as f, _open(f, passphrase) as tar:
        manifest = _manifest(tar)
        v1 = manifest.get("format_version", 1) == 1
        items = set(manifest.get("items", []))
        roots = {**planned_roots(manifest), **(roots or {})}
        previous = _aside(paths.root)
        if "projects" in items:
            _aside(projects_dir())
        dests = {"core": paths.root, "projects": projects_dir(), **{f"roots/{n}": p for n, p in roots.items()}}
        for dest in dests.values():
            dest.mkdir(parents=True, exist_ok=True)
        for member in tar:
            name = f"core/{member.name}" if v1 else member.name
            head, _, rest = name.partition("/")
            if head == "roots":
                n, _, rest = rest.partition("/")
                head = f"roots/{n}"
            if head not in dests or not rest:
                continue
            member.name = rest
            tar.extract(member, dests[head], filter=_extract_filter)
    paths.ensure()
    ensure_private_dir(paths.device.root)
    for p in paths.secrets.glob("*"):
        p.chmod(0o600)
    moves = [
        (str(PurePath(manifest.get("mensarium_home") or mensarium_home()) / "projects"), str(projects_dir())),
        *((r["path"], str(roots[int(r["id"])])) for r in manifest.get("roots", [])),
        (manifest.get("home") or str(Path.home()), str(Path.home())),
    ]
    warnings = _follow_paths(paths, moves, manifest.get("moved_to"))
    return Restored(manifest=manifest, previous=previous, warnings=warnings)


def _follow_paths(paths: CorePaths, moves: list[tuple[str, str]], moved_to: str | None) -> list[str]:
    """Point the Core's config and its device's projects at where the folders are now, and re-link git worktrees."""
    cfg = yaml.safe_load(paths.config.read_text()) or {}
    device = cfg.setdefault("device", {})
    device["roots"] = [remap(r, moves) for r in device.get("roots") or []]
    if moved_to:
        cfg.setdefault("server", {})["public_url"] = moved_to
    paths.config.write_text(yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True))
    paths.config.chmod(0o600)
    if not paths.device.config.exists() or not paths.db.exists():
        return []
    device_id = (yaml.safe_load(paths.device.config.read_text()) or {}).get("target_id")
    with sqlite3.connect(paths.db) as conn:
        rows = conn.execute("SELECT id, kind, source_path FROM projects WHERE source_target_id = ?", (device_id,)).fetchall()
        projects = [(pid, kind, remap(src, moves)) for pid, kind, src in rows]
        conn.executemany("UPDATE projects SET source_path = ? WHERE id = ?", [(src, pid) for pid, _, src in projects])
    conn.close()
    return _repair_worktrees(projects)


def _repair_worktrees(projects: list[tuple[str, str, str]]) -> list[str]:
    git = shutil.which("git")
    # Chats the Core's device runs for projects of other devices live on its own copy, repo.git.
    own = {pid for pid, _, _ in projects}
    copies = [bare for bare in sorted(projects_dir().glob("*/repo.git")) if bare.parent.name not in own]
    if (projects or copies) and not git:
        return ["git is not installed: chat copies of projects were not re-linked (install git, then run `mensarium core restore` again)"]
    warnings = []
    for pid, kind, src in projects:
        if not Path(src).is_dir():
            warnings.append(f"project folder {src} is missing on this machine")
            continue
        home = projects_dir() / pid
        base = ["-C", src] if kind == "repo" else ["--git-dir", str(home / "shadow.git")]
        if kind != "repo":
            if not (home / "shadow.git").exists():
                continue
            subprocess.run([str(git), *base, "config", "core.excludesFile", str(Path(src) / ".mensariumignore")], capture_output=True, timeout=60)
        warnings += _repair(str(git), base, home / "wt", src)
    for bare in copies:
        warnings += _repair(str(git), ["--git-dir", str(bare)], bare.parent / "wt", str(bare))
    return warnings


def _repair(git: str, base: list[str], wt: Path, name: str) -> list[str]:
    worktrees = sorted(str(p) for p in wt.glob("*") if p.is_dir())
    if not worktrees:
        return []
    result = subprocess.run([git, *base, "worktree", "repair", *worktrees], capture_output=True, text=True, timeout=300)
    return [f"project {name}: git worktree repair failed: {result.stderr.strip()[:300]}"] if result.returncode != 0 else []
