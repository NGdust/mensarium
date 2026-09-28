import asyncio
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import yaml
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mensarium.cli import backup
from mensarium.client import moving
from mensarium.client.config import ClientConfig, ClientPaths, load_client_config, save_client_config
from mensarium.contracts.protocol import CoreIdentity, CoreMoved
from mensarium.core.client_hub import ClientHub
from mensarium.core.config import CoreConfig, CorePaths, DeviceConfig, save_config
from mensarium.core.db import Database
from mensarium.shared.crypto import load_or_create_private_key, public_key_b64, sign, verify
from mensarium.shared.timeutil import iso_in


def git(cwd: Path, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def machine(home: Path) -> patch:  # type: ignore[type-arg]
    return patch.dict(os.environ, {"HOME": str(home), "MENSARIUM_HOME": str(home / ".mensarium")})


@unittest.skipUnless(shutil.which("git"), "git is not installed")
class MoveCoreTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.old, self.new = self.base / "old", self.base / "new"
        self.bundle = self.base / "move.pab"
        with machine(self.old):
            self._old_core()

    def _old_core(self) -> None:
        paths = CorePaths()
        paths.ensure()
        code = self.old / "code"
        repo = code / "app"
        repo.mkdir(parents=True)
        git(repo, "init", "-q", "-b", "main")
        (repo / "app.py").write_text("print('hi')\n")
        (repo / ".env").write_text("TOKEN=kept\n")
        (repo / "node_modules" / "lib").mkdir(parents=True)
        (repo / "node_modules" / "lib" / "big.js").write_text("x" * 5000)
        (code / "abs-link").symlink_to("/etc/hosts")
        git(repo, "add", "app.py")
        git(repo, "commit", "-qm", "init")
        wt = self.old / ".mensarium" / "projects" / "prj_1" / "wt" / "task_1"
        wt.parent.mkdir(parents=True)
        git(repo, "worktree", "add", "-q", "-b", "mensarium/chat-1", str(wt))
        (wt / "draft.py").write_text("wip\n")
        save_config(paths, CoreConfig(device=DeviceConfig(roots=[str(code)])))
        (paths.secrets / "ollama-api-key").write_text("secret")
        load_or_create_private_key(paths.signing_key)
        paths.device.ensure()
        load_or_create_private_key(paths.device.key)
        paths.device.config.write_text(yaml.safe_dump({"target_id": "tgt_dev"}))

        async def db() -> None:
            database = Database(paths.db)
            await database.connect()
            await database.execute(
                "INSERT INTO projects (id, workspace_id, name, kind, source_target_id, source_path, status, created_at, updated_at) "
                "VALUES ('prj_1', 'ws', 'app', 'repo', 'tgt_dev', ?, 'ready', '', '')",
                (str(repo),),
            )
            await database.close()

        asyncio.run(db())

    def _export(self, moved_to: str | None = "https://new.example:8787") -> dict[str, object]:
        with machine(self.old):
            paths = CorePaths()
            core, items = backup.backup_items(paths, CoreConfig.model_validate(yaml.safe_load(paths.config.read_text())))
            by_key = {i.key: i for i in items}
            self.assertIn("root:0", by_key)
            self.assertEqual(by_key["root:0"].skipped, 5000)
            return backup.export_bundle(paths, self.bundle, "pw", items, moved_to)

    def test_move_to_a_machine_with_another_home_keeps_everything(self) -> None:
        info = self._export()
        self.assertEqual(info["problems"], [])
        old_key = (self.old / ".mensarium" / "core" / "keys" / "core_ed25519.pem").read_bytes()
        shutil.rmtree(self.old)
        with machine(self.new):
            restored = backup.import_bundle(CorePaths(), self.bundle, "pw")
            paths = CorePaths()
            self.assertEqual(restored.warnings, [])
            repo = self.new / "code" / "app"
            self.assertEqual((repo / ".env").read_text(), "TOKEN=kept\n")
            self.assertFalse((repo / "node_modules").exists())
            self.assertEqual(os.readlink(self.new / "code" / "abs-link"), "/etc/hosts")
            cfg = yaml.safe_load(paths.config.read_text())
            self.assertEqual(cfg["device"]["roots"], [str(self.new / "code")])
            self.assertEqual(cfg["server"]["public_url"], "https://new.example:8787")
            self.assertEqual(paths.signing_key.read_bytes(), old_key)
            self.assertTrue(paths.device.key.exists())
            self.assertEqual((paths.secrets / "ollama-api-key").stat().st_mode & 0o777, 0o600)
            with sqlite3.connect(paths.db) as conn:
                self.assertEqual(conn.execute("SELECT source_path FROM projects").fetchone()[0], str(repo))
            wt = self.new / ".mensarium" / "projects" / "prj_1" / "wt" / "task_1"
            self.assertEqual((wt / "draft.py").read_text(), "wip\n")
            self.assertEqual(git(wt, "rev-parse", "--abbrev-ref", "HEAD"), "mensarium/chat-1")
            self.assertIn(str(wt), git(repo, "worktree", "list"))

    def test_a_folder_without_permission_goes_where_the_user_says(self) -> None:
        self._export(moved_to=None)
        with machine(self.new):
            other = self.base / "elsewhere"
            backup.import_bundle(CorePaths(), self.bundle, "pw", {0: other})
            self.assertTrue((other / "app" / "app.py").exists())
            cfg = yaml.safe_load(CorePaths().config.read_text())
            self.assertEqual(cfg["device"]["roots"], [str(other)])
            self.assertEqual(cfg["server"]["public_url"], "http://127.0.0.1:8787")

    def test_wrong_passphrase_and_truncated_bundles_are_refused(self) -> None:
        self._export()
        with machine(self.new):
            with self.assertRaisesRegex(backup.BackupError, "wrong passphrase"):
                backup.read_manifest(self.bundle, "nope")
            data = self.bundle.read_bytes()
            self.bundle.write_bytes(data[: len(data) - 10])
            with self.assertRaises(backup.BackupError):
                backup.import_bundle(CorePaths(), self.bundle, "pw")

    def test_a_version_1_bundle_still_restores(self) -> None:
        with machine(self.old):
            paths = CorePaths()
            legacy = self.base / "legacy.pab"
            buf = backup.io.BytesIO()
            with backup.tarfile.open(fileobj=buf, mode="w:gz") as tar:
                backup._add_bytes(tar, "manifest.json", json.dumps({"format_version": 1}).encode())
                tar.add(paths.config, arcname="config.yaml")
                tar.add(paths.keys, arcname="keys")
            salt, nonce = os.urandom(16), os.urandom(12)
            sealed = backup.AESGCM(backup._key("pw", salt)).encrypt(nonce, buf.getvalue(), backup.MAGIC_V1)
            legacy.write_bytes(backup.MAGIC_V1 + salt + nonce + sealed)
        with machine(self.new):
            backup.import_bundle(CorePaths(), legacy, "pw")
            self.assertTrue(CorePaths().signing_key.exists())

    def test_remap_takes_the_most_specific_move(self) -> None:
        moves = [("/home/a", "/root"), ("/home/a/.mensarium/projects", "/srv/p")]
        self.assertEqual(backup.remap("/home/a/code", moves), "/root/code")
        self.assertEqual(backup.remap("/home/a/.mensarium/projects/x", moves), "/srv/p/x")
        self.assertEqual(backup.remap("/home/ab", moves), "/home/ab")
        self.assertEqual(backup.remap("/home/a", moves), "/root")


class FollowCoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = patch.dict(os.environ, {"MENSARIUM_HOME": tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.key = Ed25519PrivateKey.generate()
        self.paths = ClientPaths()
        self.paths.ensure()
        self.cfg = ClientConfig(server="http://old:8787", ws_url="ws://old:8787/v1/clients/ws", target_id="tgt_1", workspace_id="ws",
                                name="mac", core_public_key=public_key_b64(self.key), core_fingerprint="", roots=[tmp.name])
        save_client_config(self.paths, self.cfg)

    def moved(self, key: Ed25519PrivateKey, target_id: str = "tgt_1", ttl: int = 60) -> dict[str, object]:
        msg = CoreMoved(target_id=target_id, url="http://new:8787", issued_at=iso_in(0), expires_at=iso_in(ttl), nonce="n").model_dump()
        msg["signature"] = sign(key, msg)
        return msg

    def core_at(self, key: Ed25519PrivateKey) -> patch:  # type: ignore[type-arg]
        def answer(request: httpx.Request) -> httpx.Response:
            ident = CoreIdentity(nonce=request.url.params["nonce"], core_public_key=public_key_b64(key), ws_url="ws://new:8787/v1/clients/ws")
            ident.signature = sign(key, ident.model_dump())
            return httpx.Response(200, json=ident.model_dump())

        real = httpx.AsyncClient
        return patch.object(moving.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(answer), **kw))

    def test_only_a_fresh_move_signed_by_our_core_for_us_is_accepted(self) -> None:
        self.assertIsNotNone(moving.accept(self.cfg, self.moved(self.key)))
        self.assertIsNone(moving.accept(self.cfg, self.moved(Ed25519PrivateKey.generate())))
        self.assertIsNone(moving.accept(self.cfg, self.moved(self.key, target_id="tgt_2")))
        self.assertIsNone(moving.accept(self.cfg, self.moved(self.key, ttl=-60)))

    async def test_switches_only_to_a_core_holding_the_same_key(self) -> None:
        moving.remember(self.paths, "http://new:8787")
        with self.core_at(Ed25519PrivateKey.generate()):
            self.assertFalse(await moving.follow(self.paths, self.cfg))
        self.assertEqual(self.cfg.server, "http://old:8787")
        with self.core_at(self.key):
            self.assertTrue(await moving.follow(self.paths, self.cfg))
        disk = load_client_config(self.paths)
        self.assertEqual((self.cfg.server, disk.server, disk.ws_url, disk.moved_to), ("http://new:8787", "http://new:8787", "ws://new:8787/v1/clients/ws", None))

    async def test_the_other_process_picks_up_the_switch_from_disk(self) -> None:
        stale = self.cfg.model_copy()
        with self.core_at(self.key):
            await moving.switch(self.paths, self.cfg, "http://new:8787/")
        self.assertTrue(await moving.follow(self.paths, stale))
        self.assertEqual(stale.ws_url, "ws://new:8787/v1/clients/ws")

    async def test_hub_tells_every_client_but_the_core_host(self) -> None:
        sent: dict[str, dict[str, object]] = {}

        def conn(target_id: str) -> SimpleNamespace:
            async def send_json(msg: dict[str, object]) -> None:
                sent[target_id] = msg

            return SimpleNamespace(target_id=target_id, ws=SimpleNamespace(send_json=send_json))

        hub = ClientHub(repo=None, signing_key=self.key)  # type: ignore[arg-type]
        hub.connections = {"tgt_1": conn("tgt_1"), "tgt_core": conn("tgt_core")}  # type: ignore[dict-item]
        told = await hub.announce_move("http://new:8787", 60, skip="tgt_core")
        self.assertEqual(told, {"tgt_1"})
        self.assertTrue(verify(public_key_b64(self.key), sent["tgt_1"]))
        self.assertIsNotNone(moving.accept(self.cfg, sent["tgt_1"]))


if __name__ == "__main__":
    unittest.main()
