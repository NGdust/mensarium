import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mensarium.agent_core.actions import ToolCallAction
from mensarium.agent_core.context import build_system_prompt
from mensarium.agent_core.profile import builtin_profiles
from mensarium.client.config import ClientConfig
from mensarium.client.tools import Executor, ToolError
from mensarium.contracts.protocol import ExecutionResult, TargetPolicy, ToolOutput
from mensarium.contracts.secrets import SecretRequestAnswer
from mensarium.core.config import CorePaths
from mensarium.core.orchestrator import Orchestrator, Stop
from mensarium.core.plugins import Toolbox
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
        with self.assertRaises(ToolError) as e:
            await self.executor.run("net.http", {"url": "https://x.test/?k=" + "Q" * 2100}, secrets={"K": "Q" * 2100})
        self.assertNotIn("QQQQ", str(e.exception))


class OrchestratorTests(unittest.IsolatedAsyncioTestCase):
    def core(self, secrets_store):
        core = Orchestrator.__new__(Orchestrator)
        core.workdirs, core.workspace_id, core.secrets = {}, "workspace", secrets_store
        core._task = AsyncMock(return_value={"id": "task", "mode": "full"})
        core._execute, core._await_approval = AsyncMock(), AsyncMock(return_value="apr_1")
        core.repo = SimpleNamespace(create_tool_call=AsyncMock(), audit=AsyncMock())
        core.bus = SimpleNamespace(emit=AsyncMock())
        core._observe = AsyncMock()
        return core

    async def handle(self, core, call, capabilities=True):
        profile = builtin_profiles()[0]
        policy = TargetPolicy(roots=["/workspace"], command_allowlist=["echo"], allow_full_access=True)
        target = {"id": "tgt_a", "name": "device", "agent_version": "0.81.0", "policy": policy.model_dump(),
                  "capabilities": {"tools": list(REGISTRY), "secrets": capabilities}}
        await core._handle_tool_call({"id": "task", "mode": "full"}, profile, Toolbox(profile, dict(REGISTRY), [], {}), target, policy, "step", call)

    async def test_full_access_still_asks_and_passes_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store(Path(tmp))
            await s.put("API_TOKEN", "fixture-value-123", "", ["tgt_a"])
            core = self.core(s)
            call = ToolCallAction(call_id="c", raw_arguments="{}", tool="shell.bash",
                                  arguments={"script": 'echo "$API_TOKEN"', "cwd": "/workspace", "secrets": ["API_TOKEN"]})
            await self.handle(core, call)
            core._await_approval.assert_awaited_once()
            self.assertEqual(core._execute.call_args.kwargs["secrets"], {"API_TOKEN": "fixture-value-123"})
            stored = core.repo.create_tool_call.call_args.args[0]["arguments"]
            self.assertNotIn("fixture-value-123", str(stored))

    async def test_unknown_or_foreign_secret_is_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store(Path(tmp))
            await s.put("API_TOKEN", "fixture-value-123", "", ["tgt_other"])
            core = self.core(s)
            call = ToolCallAction(call_id="c", raw_arguments="{}", tool="net.http",
                                  arguments={"url": "https://x.test/", "headers": {"Authorization": "{{secret:API_TOKEN}}"}})
            await self.handle(core, call)
            core._execute.assert_not_awaited()
            self.assertIn("not allowed on this device", core._observe.call_args.args[2])

    async def test_request_carries_values_but_not_the_secrets_key(self):
        core = Orchestrator.__new__(Orchestrator)
        core.workspace_id, core.workdirs, core.running_requests = "workspace", {}, {}
        core.cfg = SimpleNamespace(execution=SimpleNamespace(request_ttl_s=60))
        core.hub = SimpleNamespace(hello=lambda _: SimpleNamespace(policy=TargetPolicy(roots=["/workspace"], command_allowlist=[]), capabilities=SimpleNamespace(tools=[])))
        sent = {}

        async def execute(request, timeout):
            sent["request"] = request
            return ExecutionResult(request_id=request.request_id, tool_call_id="tc", status="succeeded", started_at="", finished_at="",
                                   result=ToolOutput(exit_code=0, stdout="token fixture-value-123"))

        core.hub.execute = execute
        core.repo = SimpleNamespace(update_tool_call=AsyncMock(), audit=AsyncMock())
        core.bus = SimpleNamespace(emit=AsyncMock())
        core._set_status, core._observe = AsyncMock(), AsyncMock()
        core._store_artifact = AsyncMock(return_value="art_1")
        decision = evaluate("shell.bash", {"script": "echo $API_TOKEN", "cwd": "/workspace", "secrets": ["API_TOKEN"]},
                            profile_tools=list(REGISTRY), target_tools=list(REGISTRY), required_risks=[],
                            target_policy=TargetPolicy(roots=["/workspace"], command_allowlist=[]))
        call = ToolCallAction(call_id="c", raw_arguments="{}", tool="shell.bash", arguments={})
        await core._execute({"id": "task", "trace_id": "t", "target_id": "tgt_a"}, builtin_profiles()[0], TargetPolicy(roots=["/workspace"], command_allowlist=[]),
                            call, "tc", decision, "apr_1", "ask", secrets={"API_TOKEN": "fixture-value-123"})
        self.assertNotIn("secrets", sent["request"].arguments)
        self.assertEqual(sent["request"].secrets, {"API_TOKEN": "fixture-value-123"})
        self.assertIn("[secret:API_TOKEN]", core._observe.call_args.args[2])
        self.assertNotIn("fixture-value-123", core._observe.call_args.args[2])


class RequestTests(unittest.IsolatedAsyncioTestCase):
    def core(self, s):
        core = Orchestrator.__new__(Orchestrator)
        core.secrets, core.workspace_id, core.controls, core.secret_waiters = s, "workspace", {}, {}
        core.cfg = SimpleNamespace(execution=SimpleNamespace(approval_ttl_s=60))
        core._task = AsyncMock(return_value={"id": "task", "target_id": "tgt_a"})
        core.repo = SimpleNamespace(audit=AsyncMock())
        core.bus = SimpleNamespace(emit=AsyncMock())
        core._set_status = AsyncMock()
        return core

    async def test_answer_saves_and_model_sees_only_the_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = store(Path(tmp))
            core = self.core(s)
            job = asyncio.create_task(core._request_secret("task", {"name": "API_TOKEN", "description": "for the API"}))
            await asyncio.sleep(0)
            request_id = next(iter(core.secret_waiters))
            await core.answer_secret(request_id, SecretRequestAnswer(value="fixture-value-123"))
            text = await job
            self.assertIn("API_TOKEN", text)
            self.assertNotIn("fixture-value-123", text)
            self.assertEqual(await s.resolve(["API_TOKEN"], "tgt_a"), {"API_TOKEN": "fixture-value-123"})
            self.assertIn("already saved", await core._request_secret("task", {"name": "API_TOKEN", "description": ""}))

            await s.put("OTHER_TOKEN", "other-fixture", "shared with tgt_other", ["tgt_other"])
            job2 = asyncio.create_task(core._request_secret("task", {"name": "OTHER_TOKEN", "description": "x"}))
            await asyncio.sleep(0)
            await core.answer_secret(next(iter(core.secret_waiters)), SecretRequestAnswer())
            await job2
            self.assertEqual(await s.resolve(["OTHER_TOKEN"], "tgt_a"), {"OTHER_TOKEN": "other-fixture"})
            self.assertEqual(await s.resolve(["OTHER_TOKEN"], "tgt_other"), {"OTHER_TOKEN": "other-fixture"})

    async def test_cancel_releases_the_card(self):
        with tempfile.TemporaryDirectory() as tmp:
            core = self.core(store(Path(tmp)))
            job = asyncio.create_task(core._request_secret("task", {"name": "API_TOKEN", "description": ""}))
            await asyncio.sleep(0)
            core.controls["task"] = "cancel"
            core._release_secret_waits("task", "cancel")
            with self.assertRaises(Stop):
                await job

    def test_prompt_lists_names_only(self):
        policy = TargetPolicy(roots=["/workspace"], command_allowlist=[])
        prompt = build_system_prompt(builtin_profiles()[0], "device", "linux", policy, ["shell.bash", "secrets.request"],
                                     secrets=[("API_TOKEN", "for the API")])
        self.assertIn("## Secrets", prompt)
        self.assertIn("API_TOKEN", prompt)
