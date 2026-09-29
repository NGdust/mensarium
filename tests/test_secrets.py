import tempfile
import unittest
from pathlib import Path

from mensarium.contracts.protocol import TargetPolicy
from mensarium.core.config import CorePaths
from mensarium.core.secrets import SecretError, SecretStore
from mensarium.policy_engine.engine import evaluate
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
