import asyncio
import json
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from mensarium.contracts.protocol import (
    AuthChallenge,
    AuthResponse,
    ExecutionCancel,
    ExecutionRequest,
    ExecutionResult,
    TargetHello,
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


@dataclass
class TargetConnection:
    ws: WebSocket
    target_id: str
    public_key: str
    hello: TargetHello
    pending: dict[str, asyncio.Future[ExecutionResult]] = field(default_factory=dict)
    updates: dict[str, asyncio.Future[TargetUpdateStatus]] = field(default_factory=dict)


class TargetHub:
    def __init__(self, repo: Repo, signing_key: Ed25519PrivateKey) -> None:
        self.repo = repo
        self.key = signing_key
        self.connections: dict[str, TargetConnection] = {}

    def is_online(self, target_id: str) -> bool:
        return target_id in self.connections

    def hello(self, target_id: str) -> TargetHello | None:
        conn = self.connections.get(target_id)
        return conn.hello if conn else None

    async def handle(self, ws: WebSocket) -> None:
        await ws.accept()
        conn = await self._authenticate(ws)
        if conn is None:
            return
        old = self.connections.get(conn.target_id)
        if old:
            await self._close(old, 4000, "replaced by a new connection")
        self.connections[conn.target_id] = conn
        log.info("target connected", extra={"target_id": conn.target_id})
        try:
            await ws.send_json({"type": "auth.ok", "ts": now_iso()})
            while True:
                msg = await ws.receive_json()
                await self._on_message(conn, msg)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            if self.connections.get(conn.target_id) is conn:
                del self.connections[conn.target_id]
                await self.repo.update_target(conn.target_id, {"status": "offline", "last_seen_at": now_iso()})
            waiters: list[asyncio.Future[Any]] = [*conn.pending.values(), *conn.updates.values()]
            for fut in waiters:
                if not fut.done():
                    fut.set_exception(TargetUnavailable("target disconnected"))
            log.info("target disconnected", extra={"target_id": conn.target_id})

    async def _authenticate(self, ws: WebSocket) -> TargetConnection | None:
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
        return TargetConnection(ws=ws, target_id=auth.target_id, public_key=target["public_key"], hello=hello)

    async def _on_message(self, conn: TargetConnection, msg: dict[str, Any]) -> None:
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

    async def disconnect(self, target_id: str, reason: str) -> None:
        conn = self.connections.get(target_id)
        if conn:
            await self._close(conn, 4403, reason)

    async def _close(self, conn: TargetConnection, code: int, reason: str) -> None:
        try:
            await conn.ws.close(code, reason)
        except RuntimeError:
            pass
