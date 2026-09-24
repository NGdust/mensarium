import asyncio
import json
import logging
import os
import platform
import socket
import sys
import time
from datetime import timedelta
from typing import Any

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from mensarium import __version__
from mensarium.contracts.protocol import (
    AuthChallenge,
    AuthResponse,
    Capabilities,
    ExecutionCancel,
    ExecutionRequest,
    ExecutionResult,
    Heartbeat,
    TargetHello,
    TargetInfo,
    TargetPolicy,
    ToolOutput,
    policy_snapshot_hash,
)
from mensarium.shared.crypto import canonical_json, sha256_hex, sign, verify
from mensarium.shared.timeutil import now_iso, parse_iso, utcnow
from mensarium.target.config import TargetConfig, TargetPaths
from mensarium.target.tools import ExecTimeout, Executor, ToolError

log = logging.getLogger(__name__)

TOOLS = ["files.list", "files.read", "files.search", "git.status", "git.diff", "shell.exec"]
APPROVAL_REQUIRED = {"shell.exec"}
CLOCK_SKEW = timedelta(seconds=30)
FATAL_CLOSE_CODES = {4401, 4403}


def platform_id() -> str:
    machine = platform.machine().lower().replace("aarch64", "arm64").replace("amd64", "x86_64")
    return f"{sys.platform}-{machine}"


class AuditLog:
    def __init__(self, paths: TargetPaths) -> None:
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


class TargetAgent:
    def __init__(self, cfg: TargetConfig, paths: TargetPaths, key: Ed25519PrivateKey) -> None:
        self.cfg = cfg
        self.key = key
        self.executor = Executor(cfg)
        self.audit = AuditLog(paths)
        self.policy = TargetPolicy(
            roots=[str(r) for r in self.executor.roots],
            command_allowlist=cfg.command_allowlist,
            allow_full_access=cfg.allow_full_access,
        )
        self.policy_hash = policy_snapshot_hash(self.policy, TOOLS)
        self.started_at = utcnow()
        self.seen_nonces: dict[str, float] = {}
        self.running: dict[str, asyncio.Task[None]] = {}
        self.send_lock = asyncio.Lock()
        self.ws: Any = None

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
                tools=TOOLS,
                shells=[os.path.basename(os.environ.get("SHELL", "sh"))],
                limits=self.cfg.limits,
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
        elif kind == "execution.cancel":
            if not verify(self.cfg.core_public_key, msg):
                log.warning("unsigned execution.cancel ignored")
                return
            cancel = ExecutionCancel.model_validate(msg)
            running = self.running.get(cancel.request_id)
            if running:
                running.cancel()

    def _check_request(self, req: ExecutionRequest, raw: dict[str, Any]) -> str | None:
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
        if req.policy_snapshot_hash != self.policy_hash:
            return "policy snapshot mismatch; core must refresh target policy"
        if req.tool not in TOOLS:
            return f"tool {req.tool} is not enabled on this target"
        full_access = req.mode == "full" and self.cfg.allow_full_access
        if req.tool in APPROVAL_REQUIRED and not req.approval_ref and not full_access:
            return f"tool {req.tool} requires an approval reference (full access is disabled on this device)"
        return None

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
                output = await self.executor.run(req.tool, req.arguments)
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
