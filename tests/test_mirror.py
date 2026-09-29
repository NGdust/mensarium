import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mensarium.core.mirror import Mirror, MirrorError


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class MirrorTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        (self.repo / "a.txt").write_text("one\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "one")
        self.first = git(self.repo, "rev-parse", "HEAD")
        self.mirror = Mirror("prj_1", base / "projects")

    async def test_fetch_renames_refs_and_bundle_is_incremental(self) -> None:
        await self.mirror.init()
        full = Path(self.tmp.name) / "full.bundle"
        git(self.repo, "bundle", "create", str(full), "refs/heads/main")
        await self.mirror.fetch_bundle(full, {"refs/heads/main": "refs/devices/tgt_1/heads/main"})
        self.assertEqual(await self.mirror.refs("refs/devices/"), {"refs/devices/tgt_1/heads/main": self.first})
        self.assertEqual(await self.mirror.rev("refs/devices/tgt_1/heads/main"), self.first)
        (self.repo / "a.txt").write_text("two\n")
        git(self.repo, "commit", "-qam", "two")
        second = git(self.repo, "rev-parse", "HEAD")
        inc = Path(self.tmp.name) / "inc.bundle"
        git(self.repo, "bundle", "create", str(inc), "refs/heads/main", f"^{self.first}")
        await self.mirror.fetch_bundle(inc, {"refs/heads/main": "refs/devices/tgt_1/heads/main"})
        self.assertEqual(await self.mirror.rev("refs/devices/tgt_1/heads/main"), second)
        out = Path(self.tmp.name) / "down.bundle"
        info = await self.mirror.bundle(out, {"refs/devices/tgt_1/heads/main": second}, [self.first])
        assert info is not None
        self.assertEqual((info.refs, info.prerequisites), ({"refs/devices/tgt_1/heads/main": second}, [self.first]))
        self.assertEqual(git(self.repo, "bundle", "list-heads", str(out)), f"{second} refs/devices/tgt_1/heads/main")
        self.assertIsNone(await self.mirror.bundle(out, {"refs/devices/tgt_1/heads/main": second}, [second]))
        await self.mirror.delete_ref("refs/devices/tgt_1/heads/main")
        self.assertEqual(await self.mirror.refs(), {})

    async def test_fetch_rejects_a_broken_bundle(self) -> None:
        await self.mirror.init()
        bad = Path(self.tmp.name) / "bad.bundle"
        bad.write_bytes(b"# v2 git bundle\nnot really\n")
        with self.assertRaises(MirrorError):
            await self.mirror.fetch_bundle(bad, {"refs/heads/main": "refs/devices/tgt_1/heads/main"})


if __name__ == "__main__":
    unittest.main()
