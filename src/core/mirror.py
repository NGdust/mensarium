"""The Core's bare mirror of a project: device refs under refs/devices/<target>/, chat branches under refs/heads/mensarium/."""

import asyncio
import logging
import os
import shutil
from pathlib import Path

from mensarium.contracts.projects import BundleInfo
from mensarium.shared import bundles
from mensarium.shared.gitflags import GIT_ENV, GIT_SAFE_FLAGS
from mensarium.shared.paths import ensure_private_dir, projects_dir

log = logging.getLogger(__name__)
TIMEOUT = 600


class MirrorError(Exception):
    pass


class Mirror:
    def __init__(self, project_id: str, root: Path | None = None) -> None:
        self.root = root or projects_dir()
        self.path = self.root / project_id / "mirror.git"

    @staticmethod
    def enabled() -> bool:
        return shutil.which("git") is not None

    @property
    def exists(self) -> bool:
        return (self.path / "HEAD").is_file()

    async def _git(self, *args: str, check: bool = True) -> str:
        git = shutil.which("git")
        if git is None:
            raise MirrorError("git is not installed on the Core host")
        proc = await asyncio.create_subprocess_exec(
            git, *GIT_SAFE_FLAGS, *args, cwd=self.root, env={**os.environ, **GIT_ENV, "GIT_DIR": str(self.path)},
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), TIMEOUT)
        except TimeoutError as e:
            proc.kill()
            raise MirrorError(f"git {args[0]} timed out") from e
        if check:
            if proc.returncode != 0:
                raise MirrorError((err or out).decode(errors="replace").strip()[:2000] or f"git {args[0]} failed with code {proc.returncode}")
            return out.decode(errors="replace")
        return (out + err).decode(errors="replace")

    async def init(self) -> None:
        if self.exists:
            return
        ensure_private_dir(self.path.parent)
        await self._git("init", "--bare", "--quiet", str(self.path))

    async def refs(self, prefix: str = "") -> dict[str, str]:
        out = await self._git("for-each-ref", "--format=%(refname) %(objectname)", *([prefix] if prefix else []))
        pairs = (line.partition(" ") for line in out.splitlines())
        return {name: sha for name, _, sha in pairs if name and sha}

    async def rev(self, ref: str) -> str | None:
        out = await self._git("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}", check=False)
        return out.strip() or None

    async def fetch_bundle(self, path: Path, refspecs: dict[str, str]) -> None:
        await self._git("bundle", "verify", "--quiet", str(path))
        await self._git("fetch", "--quiet", "--no-tags", str(path), *(f"+{src}:{dst}" for src, dst in refspecs.items()))

    async def bundle(self, path: Path, refs: dict[str, str], prerequisites: list[str]) -> BundleInfo | None:
        path.unlink(missing_ok=True)
        have = [sha for sha in prerequisites if await self.rev(sha)]
        out = await self._git("bundle", "create", "--quiet", str(path), *refs, *(f"^{sha}" for sha in have), check=False)
        if not path.is_file():
            if "refusing to create empty bundle" in out.lower():
                return None
            raise MirrorError(out.strip()[:2000] or "git bundle create failed")
        return bundles.describe(path, refs, have)

    async def update_ref(self, ref: str, sha: str) -> None:
        await self._git("update-ref", ref, sha)

    async def delete_ref(self, ref: str) -> None:
        await self._git("update-ref", "-d", ref, check=False)

    def delete(self) -> None:
        shutil.rmtree(self.path, ignore_errors=True)
