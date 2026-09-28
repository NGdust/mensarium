import asyncio
import json
import logging
import secrets
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any, Protocol

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from mensarium.contracts.gateway import SessionKind
from mensarium.contracts.projects import ProjectOp, ProjectSnapshot
from mensarium.contracts.protocol import (
    AuthChallenge,
    AuthResponse,
    CoreMoved,
    ExecutionCancel,
    ExecutionRequest,
    ExecutionResult,
    McpServerDef,
    TargetHello,
    TargetPlugins,
    TargetPluginsStatus,
    TargetUpdate,
    TargetUpdateStatus,
)
from mensarium.core.repo import Repo
from mensarium.shared.crypto import sign, verify
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import iso_in, now_iso

log = logging.getLogger(__name__)


class TargetUnavailable(Exception):
    pass


class ApiHandler(Protocol):
    async def handle(self, conn: "ClientConnection", msg: dict[str, Any]) -> None: ...

    def drop(self, conn: "ClientConnection") -> None: ...


@dataclass
class ClientConnection:
    ws: WebSocket
    target_id: str
    public_key: str
    hello: TargetHello
    session: SessionKind = "worker"
    pending: dict[str, asyncio.Future[ExecutionResult]] = field(default_factory=dict)
    updates: dict[str, asyncio.Future[TargetUpdateStatus]] = field(default_factory=dict)
    plugins: dict[str, asyncio.Future[TargetPluginsStatus]] = field(default_factory=dict)
    projects: dict[str, asyncio.Future[dict[str, Any]]] = field(default_factory=dict)


class ClientHub:
    def __init__(self, repo: Repo, signing_key: Ed25519PrivateKey) -> None:
        self.repo = repo
        self.key = signing_key
        self.connections: dict[str, ClientConnection] = {}
        self.gateways: dict[str, ClientConnection] = {}
        self.api: ApiHandler | None = None
        self.on_connect: Callable[[str], Coroutine[Any, Any, None]] | None = None
        self.tasks: set[asyncio.Task[None]] = set()

    def is_online(self, target_id: str) -> bool:
        return target_id in self.connections

    def hello(self, target_id: str) -> TargetHello | None:
        conn = self.connections.get(target_id)
        return conn.hello if conn else None

    def gateway_online(self, target_id: str) -> bool:
        return target_id in self.gateways

    async def handle(self, ws: WebSocket) -> None:
        await ws.accept()
        conn = await self._authenticate(ws)
        if conn is None:
            return
        if conn.session == "gateway":
            await self._handle_gateway(conn)
            return
        old = self.connections.get(conn.target_id)
        if old:
            await self._close(old, 4000, "replaced by a new connection")
        self.connections[conn.target_id] = conn
        log.info("target connected", extra={"target_id": conn.target_id})
        try:
            await ws.send_json({"type": "auth.ok", "ts": now_iso()})
            if self.on_connect:
                task: asyncio.Task[None] = asyncio.create_task(self.on_connect(conn.target_id))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
            while True:
                msg = await ws.receive_json()
                await self._on_message(conn, msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if self.connections.get(conn.target_id) is conn:
                del self.connections[conn.target_id]
                await self.repo.update_target(conn.target_id, {"status": "offline", "last_seen_at": now_iso()})
            waiters: list[asyncio.Future[Any]] = [*conn.pending.values(), *conn.updates.values(), *conn.plugins.values(), *conn.projects.values()]
            for fut in waiters:
                if not fut.done():
                    fut.set_exception(TargetUnavailable("target disconnected"))
            log.info("target disconnected", extra={"target_id": conn.target_id})

    async def _handle_gateway(self, conn: ClientConnection) -> None:
        """A gateway session only relays API frames; it never receives execution requests."""
        ws = conn.ws
        old = self.gateways.get(conn.target_id)
        if old:
            await self._close(old, 4000, "replaced by a new connection")
        self.gateways[conn.target_id] = conn
        log.info("gateway connected", extra={"target_id": conn.target_id})
        try:
            await ws.send_json({"type": "auth.ok", "ts": now_iso()})
            while True:
                msg = await ws.receive_json()
                kind = msg.get("type")
                if kind == "target.heartbeat":
                    await self.repo.update_target(conn.target_id, {"last_seen_at": now_iso()})
                elif kind in ("api.request", "api.cancel") and self.api:
                    await self.api.handle(conn, msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if self.gateways.get(conn.target_id) is conn:
                del self.gateways[conn.target_id]
            if self.api:
                self.api.drop(conn)
            log.info("gateway disconnected", extra={"target_id": conn.target_id})

    async def _authenticate(self, ws: WebSocket) -> ClientConnection | None:
        nonce = secrets.token_urlsafe(32)
        await ws.send_json(AuthChallenge(nonce=nonce).model_dump())
        try:
            auth = AuthResponse.model_validate(await asyncio.wait_for(ws.receive_json(), 15))
            target = await self.repo.get_target(auth.target_id)
            if not target or target["status"] == "revoked" or auth.nonce != nonce:
                await ws.close(4401, "unknown or revoked target")
                return None
            if not verify(target["public_key"], auth.model_dump()):
                await ws.close(4401, "bad signature")
                return None
            hello = TargetHello.model_validate(await asyncio.wait_for(ws.receive_json(), 15))
        except (TimeoutError, ValidationError, WebSocketDisconnect, json.JSONDecodeError, KeyError):
            await ws.close(4400, "handshake failed")
            return None
        if hello.target.id != auth.target_id:
            await ws.close(4400, "target id mismatch")
            return None
        if hello.session == "gateway":
            await self.repo.update_target(auth.target_id, {"last_seen_at": now_iso()})
            return ClientConnection(ws=ws, target_id=auth.target_id, public_key=target["public_key"], hello=hello, session="gateway")
        await self.repo.update_target(
            auth.target_id,
            {
                "status": "online",
                "last_seen_at": now_iso(),
                "platform": hello.target.platform,
                "hostname": hello.target.hostname,
                "agent_version": hello.target.agent_version,
                "capabilities": hello.capabilities.model_dump(),
                "policy": hello.policy.model_dump(),
            },
        )
        return ClientConnection(ws=ws, target_id=auth.target_id, public_key=target["public_key"], hello=hello)

    async def _on_message(self, conn: ClientConnection, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "target.heartbeat":
            await self.repo.update_target(conn.target_id, {"last_seen_at": now_iso()})
        elif kind == "execution.result":
            try:
                result = ExecutionResult.model_validate(msg)
            except ValidationError:
                log.warning("invalid execution.result", extra={"target_id": conn.target_id})
                return
            fut = conn.pending.pop(result.request_id, None)
            if fut is None or fut.done():
                return
            if not verify(conn.public_key, msg):
                fut.set_exception(TargetUnavailable("execution.result has an invalid signature"))
                return
            fut.set_result(result)
        elif kind == "target.update.status":
            try:
                status = TargetUpdateStatus.model_validate(msg)
            except ValidationError:
                return
            waiter = conn.updates.pop(status.request_id, None)
            if waiter and not waiter.done() and verify(conn.public_key, msg):
                waiter.set_result(status)
        elif kind == "target.plugins.status":
            try:
                answer = TargetPluginsStatus.model_validate(msg)
            except ValidationError:
                return
            plugin_waiter = conn.plugins.pop(answer.request_id, None)
            if plugin_waiter and not plugin_waiter.done() and verify(conn.public_key, msg):
                plugin_waiter.set_result(answer)
        elif kind in ("project.snapshot.status", "project.op.status"):
            project_waiter = conn.projects.pop(str(msg.get("request_id") or ""), None)
            if project_waiter is None or project_waiter.done():
                return
            if not verify(conn.public_key, msg):
                project_waiter.set_exception(TargetUnavailable("project answer has an invalid signature"))
                return
            project_waiter.set_result(msg)

    def supports(self, target_id: str, tool: str) -> bool:
        hello = self.hello(target_id)
        return bool(hello and tool in hello.capabilities.tools)

    async def request_plugins(self, target_id: str, servers: list[McpServerDef], ttl_s: int) -> TargetPluginsStatus:
        """Send a device its MCP servers; it starts them and answers with their tools (first start may download)."""
        conn = self.connections.get(target_id)
        if conn is None:
            raise TargetUnavailable("target is offline")
        msg = TargetPlugins(
            request_id=new_id("plg"),
            target_id=target_id,
            issued_at=now_iso(),
            expires_at=iso_in(ttl_s),
            nonce=secrets.token_hex(32),
            servers=servers,
        )
        msg.signature = sign(self.key, msg.model_dump())
        fut: asyncio.Future[TargetPluginsStatus] = asyncio.get_running_loop().create_future()
        conn.plugins[msg.request_id] = fut
        try:
            await conn.ws.send_json(msg.model_dump())
            return await asyncio.wait_for(fut, 300)
        except TimeoutError as e:
            raise TargetUnavailable("the device did not report its MCP servers in time") from e
        finally:
            conn.plugins.pop(msg.request_id, None)

    async def project_request(self, msg: ProjectSnapshot | ProjectOp, timeout_s: float) -> dict[str, Any]:
        conn = self.connections.get(msg.target_id)
        if conn is None:
            raise TargetUnavailable("target is offline")
        msg.signature = sign(self.key, msg.model_dump())
        fut: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        conn.projects[msg.request_id] = fut
        try:
            await conn.ws.send_json(msg.model_dump())
            return await asyncio.wait_for(fut, timeout_s)
        except TimeoutError as e:
            raise TargetUnavailable("the device did not answer the project request in time") from e
        finally:
            conn.projects.pop(msg.request_id, None)

    async def update_device(self, target: dict[str, Any], version: str, ttl_s: int) -> TargetUpdateStatus:
        """Ask a device that allows remote updates to update its agent from this Core."""
        if not (target.get("capabilities") or {}).get("remote_update"):
            raise TargetUnavailable("this agent cannot be updated remotely; run `mensarium update` on the device")
        return await self.request_update(target["id"], version, ttl_s)

    async def request_update(self, target_id: str, version: str, ttl_s: int) -> TargetUpdateStatus:
        """Ask a device to update its agent from this Core; returns the device's signed answer."""
        conn = self.connections.get(target_id)
        if conn is None:
            raise TargetUnavailable("target is offline")
        msg = TargetUpdate(
            request_id=new_id("upd"),
            target_id=target_id,
            version=version,
            issued_at=now_iso(),
            expires_at=iso_in(ttl_s),
            nonce=secrets.token_hex(32),
        )
        msg.signature = sign(self.key, msg.model_dump())
        fut: asyncio.Future[TargetUpdateStatus] = asyncio.get_running_loop().create_future()
        conn.updates[msg.request_id] = fut
        try:
            await conn.ws.send_json(msg.model_dump())
            return await asyncio.wait_for(fut, 20)
        except TimeoutError as e:
            raise TargetUnavailable("the device did not answer the update request") from e
        finally:
            conn.updates.pop(msg.request_id, None)

    async def execute(self, request: ExecutionRequest, timeout_s: float) -> ExecutionResult:
        conn = self.connections.get(request.target_id)
        if conn is None:
            raise TargetUnavailable("target is offline")
        request.signature = sign(self.key, request.model_dump())
        fut: asyncio.Future[ExecutionResult] = asyncio.get_running_loop().create_future()
        conn.pending[request.request_id] = fut
        try:
            await conn.ws.send_json(request.model_dump())
            return await asyncio.wait_for(fut, timeout_s)
        except TimeoutError as e:
            raise TargetUnavailable("no result from target before timeout") from e
        finally:
            conn.pending.pop(request.request_id, None)

    async def cancel(self, target_id: str, request_id: str) -> None:
        conn = self.connections.get(target_id)
        if conn is None:
            return
        msg = ExecutionCancel(request_id=request_id, target_id=target_id, issued_at=now_iso())
        msg.signature = sign(self.key, msg.model_dump())
        try:
            await conn.ws.send_json(msg.model_dump())
        except (RuntimeError, WebSocketDisconnect):
            pass

    async def announce_move(self, url: str, ttl_s: int, skip: str | None) -> set[str]:
        """Tell every connected worker and gateway the Core's new address; returns the targets that got it."""
        told: set[str] = set()
        for conn in [*self.connections.values(), *self.gateways.values()]:
            if conn.target_id == skip:
                continue
            msg = CoreMoved(target_id=conn.target_id, url=url, issued_at=now_iso(), expires_at=iso_in(ttl_s), nonce=secrets.token_hex(32))
            msg.signature = sign(self.key, msg.model_dump())
            try:
                await conn.ws.send_json(msg.model_dump())
                told.add(conn.target_id)
            except (RuntimeError, WebSocketDisconnect):
                pass
        return told

    async def disconnect(self, target_id: str, reason: str) -> None:
        for conn in (self.connections.get(target_id), self.gateways.get(target_id)):
            if conn:
                await self._close(conn, 4403, reason)

    async def _close(self, conn: ClientConnection, code: int, reason: str) -> None:
        try:
            await conn.ws.close(code, reason)
        except RuntimeError:
            pass
