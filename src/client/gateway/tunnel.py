"""The gateway's outgoing WebSocket to the Core: relays browser requests as `api.*` frames."""

import asyncio
import base64
import json
import logging
import socket
from dataclasses import dataclass, field
from typing import Any

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mensarium import __version__
from mensarium.client import moving
from mensarium.client.agent import FATAL_CLOSE_CODES, platform_id
from mensarium.client.config import ClientConfig, ClientPaths
from mensarium.contracts.gateway import ApiCancel, ApiChunk, ApiEnd, ApiRequest, ApiResponse
from mensarium.contracts.protocol import AuthChallenge, AuthResponse, Capabilities, Heartbeat, TargetHello, TargetInfo
from mensarium.shared.crypto import sign
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import now_iso

log = logging.getLogger(__name__)
Frame = ApiResponse | ApiChunk | ApiEnd


class CoreOffline(Exception):
    pass


@dataclass
class Call:
    id: str
    queue: asyncio.Queue[Frame] = field(default_factory=asyncio.Queue)


class Tunnel:
    def __init__(self, cfg: ClientConfig, paths: ClientPaths, key: Ed25519PrivateKey) -> None:
        self.cfg = cfg
        self.paths = paths
        self.key = key
        self.online = False
        self.rejected_reason: str | None = None
        self.calls: dict[str, Call] = {}
        self.ws: Any = None
        self.send_lock = asyncio.Lock()

    def hello(self) -> TargetHello:
        return TargetHello(
            session="gateway",
            target=TargetInfo(
                id=self.cfg.target_id,
                name=self.cfg.name,
                platform=platform_id(),
                hostname=socket.gethostname(),
                agent_version=__version__,
            ),
            capabilities=Capabilities(tools=[], gateway_port=self.cfg.gateway.port),
            policy=self.cfg.policy,
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
                    self.rejected_reason = e.rcvd.reason if e.rcvd else "rejected"
                    log.error("core rejected this client (revoked or unknown); re-pair required", extra={"code": code})
                    await asyncio.sleep(300)
                    continue
                log.warning("tunnel closed", extra={"code": code})
            except (OSError, websockets.InvalidHandshake, TimeoutError) as e:
                if await moving.follow(self.paths, self.cfg):
                    log.info("core moved; connecting to its new address", extra={"server": self.cfg.server})
                    backoff = 1.0
                    continue
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
            self.online, self.rejected_reason = True, None
            log.info("gateway connected to core", extra={"server": self.cfg.server})
            heartbeat = asyncio.create_task(self._heartbeat())
            try:
                async for raw in ws:
                    self._on_frame(json.loads(raw))
            finally:
                self.online = False
                heartbeat.cancel()
                for call in list(self.calls.values()):
                    call.queue.put_nowait(ApiEnd(id=call.id, error="core-offline"))
                self.calls.clear()

    async def _heartbeat(self) -> None:
        while True:
            await asyncio.sleep(30)
            await self._send(Heartbeat(ts=now_iso()).model_dump())

    async def _send(self, msg: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.ws.send(json.dumps(msg, ensure_ascii=False))

    def _on_frame(self, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "core.moved":
            if moved := moving.accept(self.cfg, msg):
                moving.remember(self.paths, moved.url)
                self.cfg.moved_to = moved.url
            return
        call = self.calls.get(str(msg.get("id")))
        if call is None:
            return
        if kind == "api.response":
            call.queue.put_nowait(ApiResponse.model_validate(msg))
        elif kind == "api.chunk":
            call.queue.put_nowait(ApiChunk.model_validate(msg))
        elif kind == "api.end":
            call.queue.put_nowait(ApiEnd.model_validate(msg))
            self.calls.pop(call.id, None)

    async def open(self, method: str, path: str, headers: dict[str, str], body: bytes) -> Call:
        if not self.online or self.ws is None:
            raise CoreOffline()
        call = Call(id=new_id("api"))
        self.calls[call.id] = call
        req = ApiRequest(id=call.id, method=method, path=path, headers=headers, body=base64.b64encode(body).decode())
        try:
            await self._send(req.model_dump())
        except websockets.ConnectionClosed as e:
            self.calls.pop(call.id, None)
            raise CoreOffline() from e
        return call

    async def cancel(self, call: Call) -> None:
        if self.calls.pop(call.id, None) is None:
            return
        try:
            await self._send(ApiCancel(id=call.id).model_dump())
        except (websockets.ConnectionClosed, AttributeError):
            pass
