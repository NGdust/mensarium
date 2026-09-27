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
from mensarium.client.agent import ClientAgent
from mensarium.client.config import ClientConfig
from mensarium.client.tools import Executor, ToolError
from mensarium.contracts.protocol import ExecutionRequest, TargetPolicy
from mensarium.core.orchestrator import Orchestrator, full_access
from mensarium.core.plugins import Toolbox
from mensarium.policy_engine.engine import evaluate
from mensarium.shared.crypto import public_key_b64, sign
from mensarium.shared.timeutil import iso_in, now_iso, utcnow
from mensarium.tool_runtime.registry import REGISTRY


class PolicyTests(unittest.TestCase):
    def decision(self, tool, args, mode="full", enabled=True, **kwargs):
        return evaluate(tool, args, profile_tools=list(REGISTRY), target_tools=list(REGISTRY),
                        required_risks=["write", "execute", "network", "destructive"],
                        target_policy=TargetPolicy(roots=["/workspace"], command_allowlist=["echo"],
                                                   allow_full_access=enabled), mode=mode, **kwargs)

    def test_device_operations_follow_mode(self):
        cases = [
            ("files.read", {"path": "/etc/example"}),
            ("files.write", {"path": "/workspace/.env", "content": "TOKEN=example"}),
            ("shell.exec", {"command": "/usr/bin/systemctl status example", "cwd": "/"}),
            ("shell.bash", {"script": "sudo systemctl restart example", "cwd": "/workspace"}),
        ]
        for tool, args in cases:
            with self.subTest(tool=tool):
                decision = self.decision(tool, args)
                self.assertTrue(decision.allowed, decision.reason)
                self.assertFalse(decision.requires_approval)
                self.assertFalse(self.decision(tool, args, mode="ask").allowed)
                self.assertFalse(self.decision(tool, args, enabled=False).allowed)

    def test_full_still_validates_arguments_and_disabled_tools(self):
        self.assertFalse(self.decision("files.read", {}).allowed)
        self.assertFalse(self.decision("files.read", {"path": "/etc/example"}, disabled_tools=["files.read"]).allowed)

    def test_relative_paths_stay_in_project(self):
        decision = self.decision("files.read", {"path": ".env"}, workdir="/workspace/project")
        self.assertEqual(decision.arguments["path"], "/workspace/project/.env")

    def test_versions_and_prompt_match_permissions(self):
        target = {"agent_version": "0.51.1", "policy": {"allow_full_access": True}}
        self.assertEqual(full_access(target), "outdated")
        target["agent_version"] = "0.52.0"
        self.assertEqual(full_access(target), "allowed")
        policy = TargetPolicy(roots=["/workspace"], command_allowlist=["echo"], allow_full_access=True)
        prompt = build_system_prompt(builtin_profiles()[0], "device", "linux", policy, [], mode="full")
        self.assertIn("Access mode: FULL", prompt)
        self.assertIn("/ (entire device)", prompt)
        self.assertIn("Access mode: ASK", build_system_prompt(builtin_profiles()[0], "device", "linux", policy, []))


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "workspace"
        self.root.mkdir()
        self.home = patch.dict(os.environ, {"MENSARIUM_HOME": str(self.base / "home")})
        self.home.start()
        self.addCleanup(self.home.stop)
        self.key = Ed25519PrivateKey.generate()
        self.cfg = ClientConfig(server="http://localhost", ws_url="ws://localhost", target_id="device",
                                workspace_id="workspace", name="test", core_public_key=public_key_b64(self.key),
                                core_fingerprint="test", roots=[str(self.root)], command_allowlist=["echo"])
        self.executor = Executor(self.cfg)

    async def test_write_read_outside_roots_and_return_to_ask(self):
        path = self.base / "outside" / ".env"
        args = {"path": str(path), "content": "API_KEY=test-fixture-only\n", "create_dirs": True}
        with self.assertRaises(ToolError):
            await self.executor.run("files.write", args)
        await self.executor.run("files.write", args, mode="full")
        result = await self.executor.run("files.read", {"path": str(path)}, mode="full")
        self.assertIn("test-fixture-only", result.stdout)
        with self.assertRaises(ToolError):
            await self.executor.run("files.read", {"path": str(path)})

    async def test_parallel_modes_do_not_leak(self):
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.executor.files_read
        secret = self.root / ".env"
        secret.write_text("TOKEN=fixture-only\n")

        async def read(args):
            if args.get("hold"):
                entered.set()
                await release.wait()
            return await original({"path": str(secret)})

        with patch.object(self.executor, "files_read", read):
            full = asyncio.create_task(self.executor.run("files.read", {"hold": True}, mode="full"))
            try:
                await entered.wait()
                with self.assertRaises(ToolError):
                    await self.executor.run("files.read", {})
            finally:
                release.set()
                result = await full
        self.assertIn("fixture-only", result.stdout)
        with self.assertRaises(ToolError):
            await self.executor.run("files.read", {"path": str(secret)})

    async def test_commands_and_environment(self):
        with patch.dict(os.environ, {"MENSARIUM_TEST_TOKEN": "fixture-only"}):
            args = {"command": "/bin/echo full-mode", "cwd": str(self.base)}
            with self.assertRaises(ToolError):
                await self.executor.run("shell.exec", args)
            result = await self.executor.run("shell.exec", args, mode="full")
            self.assertEqual(result.stdout.strip(), "full-mode")
            for mode, expected in [("full", "fixture-only"), ("ask", "unset")]:
                result = await self.executor.run("shell.bash", {
                    "script": 'printf %s "${MENSARIUM_TEST_TOKEN-unset}"', "cwd": str(self.root)}, mode=mode)
                self.assertEqual(result.stdout, expected)

    async def test_secret_copy_and_search(self):
        source = self.root / "source"
        source.mkdir()
        (source / ".env").write_text("TOKEN=fixture-only\n")
        for mode in ("ask", "full"):
            destination = self.root / mode
            await self.executor.run("files.copy", {"source": str(source), "destination": str(destination)}, mode=mode)
            self.assertEqual((destination / ".env").exists(), mode == "full")
        for use_rg in (True, False):
            with patch("mensarium.client.tools.shutil.which", wraps=__import__("shutil").which) as which:
                if not use_rg:
                    which.return_value = None
                result = await self.executor.run("files.search", {"path": str(source), "query": "fixture-only"}, mode="full")
                self.assertIn("fixture-only", result.stdout)
        result = await self.executor.run("files.find", {"path": str(source), "pattern": "*", "include_hidden": True}, mode="full")
        self.assertIn(".env", result.stdout)

    async def test_local_opt_out_is_enforced(self):
        self.cfg.allow_full_access = False
        with self.assertRaisesRegex(ToolError, "full access is disabled"):
            await self.executor.run("shell.exec", {"command": "echo test", "cwd": str(self.root)}, mode="full")

    async def test_signed_requests_preserve_authentication_and_mode(self):
        agent = ClientAgent.__new__(ClientAgent)
        agent.cfg, agent.executor = self.cfg, self.executor
        agent.started_at, agent.seen_nonces = utcnow(), {}
        agent.tools, agent.policy_hash = list(REGISTRY), "test-policy"
        req = ExecutionRequest(request_id="r", trace_id="t", workspace_id="workspace", task_id="task",
                               target_id="device", tool_call_id="tc", issued_at=now_iso(), expires_at=iso_in(60),
                               nonce="unique", policy_snapshot_hash="test-policy", tool="shell.exec",
                               arguments={"command": "echo ok", "cwd": str(self.root)}, mode="full")
        req.signature = sign(self.key, req.model_dump())
        tampered = req.model_copy(update={"mode": "ask"})
        self.assertEqual(agent._check_request(tampered, tampered.model_dump()), "invalid signature")
        self.assertIsNone(agent._check_request(req, req.model_dump()))
        self.assertEqual(agent._check_request(req, req.model_dump()), "replayed nonce")

    async def test_core_passes_full_mode_without_approval(self):
        profile = builtin_profiles()[0]
        task = {"id": "task", "mode": "full"}
        target = {"name": "device", "agent_version": "0.52.0", "policy": self.cfg.policy.model_dump(),
                  "capabilities": {"tools": list(REGISTRY)}}
        core = Orchestrator.__new__(Orchestrator)
        core.workdirs, core.workspace_id = {}, "workspace"
        core._task, core._execute, core._await_approval = AsyncMock(return_value=task), AsyncMock(), AsyncMock()
        core.repo = SimpleNamespace(create_tool_call=AsyncMock(), audit=AsyncMock())
        core.bus = SimpleNamespace(emit=AsyncMock())
        core._observe = AsyncMock()
        toolbox = Toolbox(profile, dict(REGISTRY), [], {})
        call = ToolCallAction(call_id="call", raw_arguments="{}", tool="shell.bash", arguments={"script": "sudo systemctl status example", "cwd": "/"})
        await core._handle_tool_call(task, profile, toolbox, target, self.cfg.policy, "step", call)
        core._await_approval.assert_not_awaited()
        core._execute.assert_awaited_once()
        self.assertEqual(core._execute.call_args.args[-1], "full")
        self.assertEqual(core._execute.call_args.args[-3].risk, "privileged")


if __name__ == "__main__":
    unittest.main()
