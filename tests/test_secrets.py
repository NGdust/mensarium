import tempfile
import unittest
from pathlib import Path

from mensarium.core.config import CorePaths
from mensarium.core.secrets import SecretError, SecretStore


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
