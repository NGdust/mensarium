import asyncio
import json
import logging
import os
import platform
import socket
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from mensarium import __version__
from mensarium.client import desktop
from mensarium.client.config import ClientConfig, ClientPaths
from mensarium.client.mcp_host import McpHost
from mensarium.client.projects import ProjectHost
from mensarium.client.tools import ExecTimeout, Executor, ToolError
from mensarium.contracts.projects import ProjectOp, ProjectOpStatus, ProjectSnapshot, ProjectSnapshotStatus
from mensarium.contracts.protocol import (
    AuthChallenge,
    AuthResponse,
    Capabilities,
    ExecutionCancel,
    ExecutionRequest,
    ExecutionResult,
    Heartbeat,
    McpServerStatus,
    TargetHello,
    TargetInfo,
    TargetPlugins,
    TargetPluginsStatus,
    TargetPolicy,
    TargetUpdate,
    TargetUpdateStatus,
    ToolOutput,
    policy_snapshot_hash,
)
from mensarium.shared.crypto import canonical_json, sha256_hex, sign, verify
from mensarium.shared.timeutil import now_iso, parse_iso, utcnow

log = logging.getLogger(__name__)

TOOLS = [
    "files.list", "files.read", "files.search", "files.stat", "files.find",
    "files.write", "files.edit", "files.mkdir", "files.move", "files.copy", "files.delete",
    "git.status", "git.diff", "system.info", "process.list", "process.kill", "net.ports", "net.http", "shell.exec",
]  # fmt: skip
APPROVAL_REQUIRED = {
    "files.write", "files.edit", "files.mkdir", "files.move", "files.copy", "files.delete", "process.kill", "net.http",
    "shell.exec", "shell.bash", "screen.capture", "input.mouse", "input.type", "input.key", "app.open", "system.volume",
}  # fmt: skip
CLOCK_SKEW = timedelta(seconds=30)
FATAL_CLOSE_CODES = {4401, 4403}


def updater() -> Path:
    """The `mensarium` command of this installation; remote updates need an install.sh setup."""
    return Path(sys.executable).parent / "mensarium"


def platform_id() -> str:
    machine = platform.machine().lower().replace("aarch64", "arm64").replace("amd64", "x86_64")
    return f"{sys.platform}-{machine}"


class AuditLog:
    def __init__(self, paths: ClientPaths) -> None:
        self.path = paths.audit
        self.prev = "sha256:genesis"
        if self.path.exists():
            with self.path.open() as f:
                for line in f:
                    if line.strip():
                        self.prev = json.loads(line)["hash"]

    def append(self, entry: dict[str, Any]) -> str:
        body = {**entry, "ts": now_iso(), "prev": self.prev}
        body["hash"] = sha256_hex(canonical_json(body))
        with self.path.open("a") as f:
            f.write(json.dumps(body, ensure_ascii=False) + "\n")
        self.prev = body["hash"]
        return str(body["hash"])


class ClientAgent:
    def __init__(self, cfg: ClientConfig, paths: ClientPaths, key: Ed25519PrivateKey) -> None:
        self.cfg = cfg
        self.key = key
        self.executor = Executor(cfg)
        self.audit = AuditLog(paths)
        self.mcp = McpHost(cfg, self.executor.roots, paths.plugins)
        self.executor.mcp = self.mcp
        self.projects = ProjectHost(self.executor)
        self.tools = (
            TOOLS
            + (["shell.bash"] if cfg.allow_shell else [])
            + desktop.available_tools()
            + (["mcp.call"] if cfg.allow_remote_plugins else [])
        )
        self.permissions = desktop.ensure_permissions(paths.permissions, __version__)
        if any(v is False for v in self.permissions.values()):
            log.warning("desktop permissions missing", extra={"permissions": self.permissions})
        self.policy = TargetPolicy(
            roots=[str(r) for r in self.executor.roots],
            command_allowlist=cfg.command_allowlist,
            allow_full_access=cfg.allow_full_access,
        )
        self.policy_hash = policy_snapshot_hash(self.policy, self.tools)
        self.started_at = utcnow()
        self.seen_nonces: dict[str, float] = {}
        self.running: dict[str, asyncio.Task[None]] = {}
        self.send_lock = asyncio.Lock()
        self.ws: Any = None
        self.updating: asyncio.Task[None] | None = None
        self.syncing: set[asyncio.Task[None]] = set()

    def hello(self) -> TargetHello:
        return TargetHello(
            target=TargetInfo(
                id=self.cfg.target_id,
                name=self.cfg.name,
                platform=platform_id(),
                hostname=socket.gethostname(),
                agent_version=__version__,
            ),
            capabilities=Capabilities(
                tools=self.tools,
                shells=[os.path.basename(os.environ.get("SHELL", "sh"))],
                desktop=desktop.permissions(),
                limits=self.cfg.limits,
                remote_update=self.cfg.allow_remote_update and updater().exists(),
                projects=self.projects.enabled,
                projects_root=str(self.projects.root) if self.projects.enabled else None,
            ),
            policy=self.policy,
        )

    async def run_forever(self) -> None:
        backoff = 1.0
        while True:
            try:
                await self._session()
                backoff = 1.0
            except websockets.ConnectionClosed as e:
                code = e.rcvd.code if e.rcvd else None
                if code in FATAL_CLOSE_CODES:
                    log.error("core rejected this target (revoked or unknown); re-pair required", extra={"code": code})
                    await asyncio.sleep(300)
                    continue
                log.warning("connection closed", extra={"code": code})
            except (OSError, websockets.InvalidHandshake, TimeoutError) as e:
                log.warning("cannot connect to core", extra={"error": str(e), "retry_in_s": backoff})
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30)

    async def _session(self) -> None:
        async with websockets.connect(self.cfg.ws_url, ping_interval=20, max_size=64 * 1024 * 1024) as ws:
            self.ws = ws
            challenge = AuthChallenge.model_validate(json.loads(await asyncio.wait_for(ws.recv(), 15)))
            auth = AuthResponse(target_id=self.cfg.target_id, nonce=challenge.nonce)
            auth.signature = sign(self.key, auth.model_dump())
            await ws.send(auth.model_dump_json())
            await ws.send(self.hello().model_dump_json())
            ok = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if ok.get("type") != "auth.ok":
                raise OSError(f"unexpected handshake reply: {ok}")
            log.info("connected to core", extra={"server": self.cfg.server, "target_id": self.cfg.target_id})
            heartbeat = asyncio.create_task(self._heartbeat())
            try:
                async for raw in ws:
                    await self._on_message(json.loads(raw))
            finally:
                heartbeat.cancel()
                for task in self.running.values():
                    task.cancel()

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(30)
            await self._send(Heartbeat(ts=now_iso()).model_dump())

    async def _send(self, msg: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.ws.send(json.dumps(msg, ensure_ascii=False))

    async def _on_message(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "execution.request":
            try:
                req = ExecutionRequest.model_validate(msg)
            except ValidationError as e:
                log.warning("invalid execution.request", extra={"error": str(e)})
                return
            task = asyncio.create_task(self._execute(req, msg))
            self.running[req.request_id] = task
            task.add_done_callback(lambda _: self.running.pop(req.request_id, None))
        elif kind == "target.plugins":
            task = asyncio.create_task(self._plugins(msg))
            self.syncing.add(task)
            task.add_done_callback(self.syncing.discard)
        elif kind == "target.update":
            if self.updating and not self.updating.done():
                await self._send_status(str(msg.get("request_id")), "rejected", "an update is already running")
                return
            self.updating = asyncio.create_task(self._update(msg))
        elif kind in ("project.snapshot", "project.op"):
            task = asyncio.create_task(self._project(msg))
            self.syncing.add(task)
            task.add_done_callback(self.syncing.discard)
        elif kind == "execution.cancel":
            if not verify(self.cfg.core_public_key, msg):
                log.warning("unsigned execution.cancel ignored")
                return
            cancel = ExecutionCancel.model_validate(msg)
            running = self.running.get(cancel.request_id)
            if running:
                running.cancel()

    def _check_signed(
        self, req: ExecutionRequest | TargetUpdate | TargetPlugins | ProjectSnapshot | ProjectOp, raw: dict[str, Any]
    ) -> str | None:
        """Signature, addressee, freshness and replay checks shared by every command from the Core."""
        if not verify(self.cfg.core_public_key, raw):
            return "invalid signature"
        if req.target_id != self.cfg.target_id:
            return "request is addressed to another target"
        now = utcnow()
        issued, expires = parse_iso(req.issued_at), parse_iso(req.expires_at)
        if expires < now:
            return "request expired"
        if issued > now + CLOCK_SKEW or issued < self.started_at - CLOCK_SKEW:
            return "request issued_at is outside the accepted window"
        mono = time.monotonic()
        self.seen_nonces = {n: t for n, t in self.seen_nonces.items() if t > mono}
        if req.nonce in self.seen_nonces:
            return "replayed nonce"
        self.seen_nonces[req.nonce] = mono + (expires - now).total_seconds() + CLOCK_SKEW.total_seconds()
        return None

    def _check_request(self, req: ExecutionRequest, raw: dict[str, Any]) -> str | None:
        if reason := self._check_signed(req, raw):
            return reason
        if req.policy_snapshot_hash != self.policy_hash:
            return "policy snapshot mismatch; core must refresh target policy"
        if req.tool not in self.tools:
            return f"tool {req.tool} is not enabled on this target"
        if req.workdir:
            try:
                self.executor.workdir(req.workdir)
            except ToolError as e:
                return str(e)
        full_access = req.mode == "full" and self.cfg.allow_full_access
        needs_approval = req.tool in APPROVAL_REQUIRED or (
            req.tool == "mcp.call" and self.mcp.risk(str(req.arguments.get("server"))) != "read"
        )
        if needs_approval and not req.approval_ref and not full_access:
            return f"tool {req.tool} requires an approval reference (full access is disabled on this device)"
        return None

    async def _update(self, raw: dict[str, Any]) -> None:
        """Run `mensarium update` in its own session; a service restart replaces this process, otherwise re-exec."""
        try:
            req = TargetUpdate.model_validate(raw)
        except ValidationError as e:
            log.warning("invalid target.update", extra={"error": str(e)})
            return
        reason = self._check_signed(req, raw)
        if not reason and not self.cfg.allow_remote_update:
            reason = "remote updates are disabled on this device (allow_remote_update)"
        if not reason and not updater().exists():
            reason = "this agent was not installed with install.sh; update it manually"
        self.audit.append({"request_id": req.request_id, "action": "update", "version": req.version, "status": "rejected" if reason else "started", "error": reason})
        await self._send_status(req.request_id, "rejected" if reason else "started", reason or "")
        if reason:
            log.warning("update request rejected", extra={"reason": reason})
            return
        log.info("updating agent", extra={"version": req.version, "server": self.cfg.server})
        proc = await asyncio.create_subprocess_exec(
            str(updater()), "update", "--source", self.cfg.server, start_new_session=True, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await proc.communicate()
        if proc.returncode != 0:
            detail = out.decode(errors="replace").strip()[-400:]
            log.error("update failed", extra={"output": detail})
            await self._send_status(req.request_id, "failed", detail)
            return
        log.info("update installed; restarting the agent")
        os.execv(sys.executable, [sys.executable, *sys.argv])

    async def _plugins(self, raw: dict[str, Any]) -> None:
        """Start, keep or stop the MCP servers the Core placed here and report their tools."""
        try:
            req = TargetPlugins.model_validate(raw)
        except ValidationError as e:
            log.warning("invalid target.plugins", extra={"error": str(e)})
            return
        reason = self._check_signed(req, raw)
        if not reason and not self.cfg.allow_remote_plugins:
            reason = "plugins from the Core are disabled on this device (allow_remote_plugins)"
        if reason:
            log.warning("plugins request rejected", extra={"reason": reason})
            states = [McpServerStatus(name=d.name, state="rejected", error=reason) for d in req.servers]
        else:
            states = await self.mcp.apply(req.servers)
        self.audit.append({"request_id": req.request_id, "action": "plugins", "servers": [s.name for s in states], "error": reason})
        answer = TargetPluginsStatus(request_id=req.request_id, servers=states)
        answer.signature = sign(self.key, answer.model_dump())
        try:
            await self._send(answer.model_dump())
        except websockets.ConnectionClosed:
            log.warning("plugins status not delivered: connection closed")

    async def _project(self, raw: dict[str, Any]) -> None:
        answer: ProjectSnapshotStatus | ProjectOpStatus
        try:
            req = ProjectSnapshot.model_validate(raw) if raw.get("type") == "project.snapshot" else ProjectOp.model_validate(raw)
        except ValidationError as e:
            log.warning("invalid project request", extra={"type": raw.get("type"), "error": str(e)})
            return
        reason = self._check_signed(req, raw)
        if isinstance(req, ProjectSnapshot):
            answer = (
                ProjectSnapshotStatus(request_id=req.request_id, project_id=req.project_id, state="error", detail=reason)
                if reason
                else await self.projects.snapshot(req)
            )
        else:
            answer = (
                ProjectOpStatus(request_id=req.request_id, project_id=req.project_id, task_id=req.task_id, op=req.op, state="error", detail=reason)
                if reason
                else await self.projects.op(req)
            )
        answer.signature = sign(self.key, answer.model_dump())
        try:
            await self._send(answer.model_dump())
        except websockets.ConnectionClosed:
            log.warning("project answer not delivered: connection closed", extra={"request_id": answer.request_id})

    async def _send_status(self, request_id: str, status: str, detail: str) -> None:
        msg = TargetUpdateStatus(request_id=request_id, status=status, detail=detail)  # type: ignore[arg-type]
        msg.signature = sign(self.key, msg.model_dump())
        try:
            await self._send(msg.model_dump())
        except websockets.ConnectionClosed:
            pass

    async def _execute(self, req: ExecutionRequest, raw: dict[str, Any]) -> None:
        started = now_iso()
        rejection = self._check_request(req, raw)
        output = ToolOutput()
        error: str | None = None
        if rejection:
            status = "rejected"
            error = rejection
            log.warning("execution request rejected", extra={"request_id": req.request_id, "reason": rejection})
        else:
            try:
                workdir = self.executor.workdir(req.workdir) if req.workdir else None
                output = await self.executor.run(req.tool, req.arguments, workdir)
                status = "succeeded" if output.exit_code in (0, None) else "failed"
            except ToolError as e:
                status, error = "failed", str(e)
            except ExecTimeout as e:
                status, error = "timeout", str(e)
            except asyncio.CancelledError:
                status, error = "canceled", "canceled by core"
            except Exception as e:
                log.exception("tool crashed")
                status, error = "failed", f"{type(e).__name__}: {e}"
        audit_hash = self.audit.append(
            {
                "request_id": req.request_id,
                "task_id": req.task_id,
                "tool_call_id": req.tool_call_id,
                "tool": req.tool,
                "arguments_hash": sha256_hex(canonical_json(req.arguments)),
                "approval_ref": req.approval_ref,
                "mode": req.mode,
                "status": status,
                "exit_code": output.exit_code,
                "error": error,
            }
        )
        result = ExecutionResult(
            request_id=req.request_id,
            tool_call_id=req.tool_call_id,
            status=status,  # type: ignore[arg-type]
            started_at=started,
            finished_at=now_iso(),
            result=output,
            error=error,
            target_audit_hash=audit_hash,
        )
        result.signature = sign(self.key, result.model_dump())
        try:
            await self._send(result.model_dump())
        except websockets.ConnectionClosed:
            log.warning("result not delivered: connection closed", extra={"request_id": req.request_id})
