import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mensarium.client.config import ClientConfig
from mensarium.client.tools import Executor, ToolError
from mensarium.contracts.protocol import TargetPolicy
from mensarium.core.config import CorePaths
from mensarium.core.secrets import SecretError, SecretStore
from mensarium.policy_engine.engine import evaluate
from mensarium.shared.crypto import public_key_b64
from mensarium.shared.secret_refs import fill_secrets, mask_secrets
from mensarium.tool_runtime.registry import REGISTRY


class FakeRepo:
    def __init__(self):
        self.kv = {}

    async def get_setting(self, key):
        return self.kv.get(key)

    async def set_setting(self, key, value):
        self.kv[key] = value


def store(base: Path) -> SecretStore:
    paths = CorePaths(base)
    paths.secrets.mkdir(parents=True, exist_ok=True)
    return SecretStore(paths, FakeRepo())


class StoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_put_resolve_and_device_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store(Path(tmp))
            await s.put("GITHUB_TOKEN", " ghp_fixture \n", "GitHub", ["tgt_a"])
            self.assertEqual(await s.resolve(["GITHUB_TOKEN"], "tgt_a"), {"GITHUB_TOKEN": "ghp_fixture"})
            with self.assertRaisesRegex(SecretError, "not allowed on this device"):
                await s.resolve(["GITHUB_TOKEN"], "tgt_b")
            with self.assertRaisesRegex(SecretError, "not defined"):
                await s.resolve(["OTHER"], "tgt_a")
            await s.put("GITHUB_TOKEN", None, "GitHub PAT", ["*"])  # keeps the value
            self.assertEqual(await s.resolve(["GITHUB_TOKEN"], "tgt_b"), {"GITHUB_TOKEN": "ghp_fixture"})
            self.assertNotIn("ghp_fixture", str(await s.all()))
            for bad in ("PATH", "lower", "MENSARIUM_X"):
                with self.assertRaises(SecretError):
                    await s.put(bad, "v", "", ["*"])
            await s.delete("GITHUB_TOKEN")
            self.assertEqual(await s.all(), [])


class RefsTests(unittest.TestCase):
    def decision(self, tool, args):
        return evaluate(tool, args, profile_tools=list(REGISTRY), target_tools=list(REGISTRY),
                        required_risks=["write", "execute", "network", "destructive"],
                        target_policy=TargetPolicy(roots=["/workspace"], command_allowlist=["echo"]))

    def test_names_from_shell_and_http(self):
        bash = self.decision("shell.bash", {"script": 'curl -H "x: $A_KEY" x', "cwd": "/workspace", "secrets": ["A_KEY"]})
        self.assertEqual(bash.secrets, ["A_KEY"])
        http = self.decision("net.http", {"url": "https://x.test/?k={{secret:B_KEY}}", "headers": {"Authorization": "Bearer {{secret:A_KEY}}"}})
        self.assertEqual(sorted(http.secrets), ["A_KEY", "B_KEY"])
        filled = fill_secrets(http.arguments, {"A_KEY": "aaaa", "B_KEY": "bbbb"})
        self.assertEqual(filled["headers"]["Authorization"], "Bearer aaaa")
        self.assertIn("{{secret:A_KEY}}", http.arguments["headers"]["Authorization"])
        self.assertEqual(mask_secrets("x aaaa y", {"A_KEY": "aaaa"}), "x [secret:A_KEY] y")


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "workspace"
        self.root.mkdir()
        home = patch.dict(os.environ, {"MENSARIUM_HOME": str(Path(self.tmp.name) / "home")})
        home.start()
        self.addCleanup(home.stop)
        cfg = ClientConfig(server="http://localhost", ws_url="ws://localhost", target_id="device", workspace_id="workspace",
                           name="test", core_public_key=public_key_b64(Ed25519PrivateKey.generate()), core_fingerprint="test",
                           roots=[str(self.root)], command_allowlist=["echo"])
        self.executor = Executor(cfg)

    async def test_env_and_masking(self):
        values = {"API_TOKEN": "fixture-value-123"}
        result = await self.executor.run("shell.bash", {"script": 'printf "%s" "$API_TOKEN"; echo "$API_TOKEN" >&2', "cwd": str(self.root)}, secrets=values)
        self.assertEqual(result.stdout, "[secret:API_TOKEN]")
        self.assertIn("[secret:API_TOKEN]", result.stderr)
        with self.assertRaises(ToolError) as e:
            await self.executor.run("shell.bash", {"script": "exit 0", "cwd": "/nope-fixture-value-123"}, secrets=values)
        self.assertNotIn("fixture-value-123", str(e.exception))
