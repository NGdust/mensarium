import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mensarium.client.config import ClientConfig
from mensarium.client.tools import Executor
from mensarium.client.undo import UndoSlot, apply_undo
from mensarium.shared.crypto import public_key_b64


class UndoSlotTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.root = base / "workspace"
        self.root.mkdir()
        self.root = self.root.resolve()
        home = patch.dict(os.environ, {"MENSARIUM_HOME": str(base / "home")})
        home.start()
        self.addCleanup(home.stop)
        self.undo = base / "undo"
        key = Ed25519PrivateKey.generate()
        cfg = ClientConfig(server="http://localhost", ws_url="ws://localhost", target_id="device", workspace_id="workspace", name="test",
                           core_public_key=public_key_b64(key), core_fingerprint="test", roots=[str(self.root)], command_allowlist=["echo"])
        self.executor = Executor(cfg)
        (self.root / "app.py").write_text("print('hi')\n")

    async def run_tool(self, tool: str, args: dict, tc: str) -> bool:
        return (await self.executor.run(tool, args, self.root, undo=UndoSlot(self.undo, "chat", tc, tool, "ask"))).undo

    async def test_file_write_and_delete_roll_back(self):
        self.assertTrue(await self.run_tool("files.write", {"path": "app.py", "content": "print('new')\n"}, "tc_w"))
        self.assertTrue(await self.run_tool("files.write", {"path": "fresh.txt", "content": "x"}, "tc_n"))
        self.assertTrue(await self.run_tool("files.delete", {"path": "app.py"}, "tc_d"))
        self.assertFalse((self.root / "app.py").exists())
        self.assertEqual(apply_undo(self.undo, "chat", "tc_d"), [str(self.root / "app.py")])
        self.assertEqual((self.root / "app.py").read_text(), "print('new')\n")
        apply_undo(self.undo, "chat", "tc_w")
        self.assertEqual((self.root / "app.py").read_text(), "print('hi')\n")
        apply_undo(self.undo, "chat", "tc_n")
        self.assertFalse((self.root / "fresh.txt").exists())
        self.assertFalse((self.undo / "chat" / "tc_w").exists())

    async def test_shell_rolls_back_a_git_worktree_but_not_ignored_files(self):
        self.assertFalse(await self.run_tool("shell.bash", {"script": "true"}, "tc_plain"))
        git = lambda *a: subprocess.run(["git", *a], cwd=self.root, check=True, capture_output=True)  # noqa: E731
        git("init", "-q")
        (self.root / ".gitignore").write_text("build/\n")
        git("add", "-A")
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "init")
        self.assertTrue(await self.run_tool("shell.bash", {"script": "mkdir -p build && echo out > build/out && echo x > new.txt && echo y >> app.py"}, "tc_sh"))
        (self.root / "later.txt").write_text("kept")
        restored = apply_undo(self.undo, "chat", "tc_sh")
        self.assertEqual(sorted(restored), [str(self.root / "app.py"), str(self.root / "new.txt")])
        self.assertTrue((self.root / "later.txt").exists())
        self.assertEqual((self.root / "app.py").read_text(), "print('hi')\n")
        self.assertFalse((self.root / "new.txt").exists())
        self.assertTrue((self.root / "build" / "out").exists())


class UndoCoreTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, Mock

        from mensarium.contracts.protocol import ExecutionResult, TargetPolicy, ToolOutput
        from mensarium.core.db import Database
        from mensarium.core.events import EventBus
        from mensarium.core.orchestrator import Orchestrator
        from mensarium.core.repo import Repo
        from mensarium.shared.timeutil import now_iso

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Database(Path(self.tmp.name) / "test.db")
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.repo = Repo(self.db)
        now = now_iso()
        await self.repo.create_task({"id": "chat", "workspace_id": "ws", "profile_id": "profile", "target_id": "device", "input": "edit app.py",
                                     "status": "SUCCEEDED", "trace_id": "trace", "created_at": now, "updated_at": now})
        await self.db.insert("tool_calls", {"id": "tc_1", "task_id": "chat", "task_step_id": "step", "tool_name": "files.edit", "arguments": "{}",
                                            "risk": "write", "display": "app.py", "status": "succeeded", "undo": "ready", "created_at": now, "updated_at": now})
        self.core = Orchestrator.__new__(Orchestrator)
        self.core.repo, self.core.bus, self.core.workspace_id = self.repo, EventBus(self.repo), "ws"
        self.core.runners, self.core.busy, self.core.projects = {}, set(), None
        self.core.cfg = SimpleNamespace(execution=SimpleNamespace(request_ttl_s=60))
        hello = SimpleNamespace(policy=TargetPolicy(roots=[], command_allowlist=[]), capabilities=SimpleNamespace(tools=["files.edit", "undo.apply"]))
        result = ExecutionResult(request_id="r", tool_call_id="tc_1", status="succeeded", started_at=now, finished_at=now, result=ToolOutput(stdout="restored:\n/w/app.py"))
        self.core.hub = Mock(hello=Mock(return_value=hello), execute=AsyncMock(return_value=result))

    async def test_undo_marks_the_call_tells_the_model_and_runs_once(self):
        from mensarium.core.orchestrator import TaskError

        out = await self.core.undo("chat", "tc_1")
        self.assertIn("/w/app.py", out["output"])
        request = self.core.hub.execute.await_args.args[0]
        self.assertEqual((request.tool, request.arguments, request.mode), ("undo.apply", {"task_id": "chat", "tool_call_id": "tc_1"}, "ask"))
        self.assertEqual((await self.repo.get_tool_call("tc_1"))["undo"], "done")
        self.assertEqual([e["event"] for e in await self.repo.list_events("chat")], ["tool_call.undone"])
        step = (await self.repo.list_steps("chat"))[-1]
        self.assertTrue(step["input"]["harness"])
        self.assertIn("files.edit", step["input"]["text"])
        with self.assertRaises(TaskError):
            await self.core.undo("chat", "tc_1")
