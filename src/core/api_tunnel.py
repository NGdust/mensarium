"""Serves `api.request` frames from a gateway session by calling the Core's own ASGI app in-process."""

import asyncio
import base64
import logging
from typing import Any

from fastapi import WebSocketDisconnect
from pydantic import BaseModel, ValidationError

from mensarium.contracts.gateway import (
    GATEWAY_SCOPE_KEY,
    MAX_REQUEST_BODY,
    RESPONSE_HEADERS,
    ApiChunk,
    ApiEnd,
    ApiRequest,
    ApiResponse,
)
from mensarium.core.client_hub import ClientConnection

log = logging.getLogger(__name__)
CANCEL_GRACE_S = 5


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


class _Call:
    def __init__(self, conn: ClientConnection, req: ApiRequest) -> None:
        self.conn = conn
        self.req = req
        self.body = base64.b64decode(req.body) if req.body else b""
        self.disconnected = asyncio.Event()
        self.body_sent = False
        self.started: dict[str, Any] | None = None
        self.task: asyncio.Task[None] | None = None


class ApiTunnel:
    def __init__(self, app: Any) -> None:
        self.app = app
        self.calls: dict[tuple[int, str], _Call] = {}

    async def handle(self, conn: ClientConnection, msg: dict[str, Any]) -> None:
        kind = msg.get("type")
        if kind == "api.request":
            try:
                req = ApiRequest.model_validate(msg)
            except ValidationError as e:
                log.warning("invalid api.request", extra={"target_id": conn.target_id, "error": str(e)})
                return
            call = _Call(conn, req)
            key = (id(conn), req.id)
            call.task = asyncio.create_task(self._serve(call))
            self.calls[key] = call
            call.task.add_done_callback(lambda _: self.calls.pop(key, None))
        elif kind == "api.cancel":
            pending = self.calls.get((id(conn), str(msg.get("id"))))
            if pending:
                self._cancel(pending)

    def drop(self, conn: ClientConnection) -> None:
        for (cid, _), call in list(self.calls.items()):
            if cid == id(conn):
                self._cancel(call)

    def _cancel(self, call: _Call) -> None:
        """Let a streaming handler see the disconnect first; force-cancel only if it ignores it."""
        call.disconnected.set()
        task = call.task

        def force() -> None:
            if task and not task.done():
                task.cancel()

        asyncio.get_running_loop().call_later(CANCEL_GRACE_S, force)

    async def _serve(self, call: _Call) -> None:
        conn, req = call.conn, call.req
        if len(call.body) > MAX_REQUEST_BODY:
            body = _b64(b'{"detail":"request body too large"}')
            await self._send(conn, ApiResponse(id=req.id, status=413, headers={"content-type": "application/json"}, body=body))
            await self._send(conn, ApiEnd(id=req.id))
            return
        path, _, query = req.path.partition("?")
        scope: dict[str, Any] = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": req.method.upper(),
            "scheme": "http",
            "path": path,
            "raw_path": path.encode(),
            "query_string": query.encode(),
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in req.headers.items()],
            "client": ("gateway", 0),
            "server": ("core", 0),
            "state": {},
            GATEWAY_SCOPE_KEY: conn.target_id,
        }

        async def receive() -> dict[str, Any]:
            if not call.body_sent:
                call.body_sent = True
                return {"type": "http.request", "body": call.body, "more_body": False}
            await call.disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                call.started = message
                return
            if message["type"] != "http.response.body":
                return
            body, more = message.get("body", b""), bool(message.get("more_body", False))
            if call.started is not None:
                headers = {
                    k.decode(): v.decode() for k, v in call.started.get("headers", []) if k.decode().lower() in RESPONSE_HEADERS
                }
                await self._send(conn, ApiResponse(id=req.id, status=call.started["status"], headers=headers, body=_b64(body), stream=more))
                call.started = None
            elif body:
                await self._send(conn, ApiChunk(id=req.id, body=_b64(body)))
            if not more:
                await self._send(conn, ApiEnd(id=req.id))

        try:
            await self.app(scope, receive, send)
        except asyncio.CancelledError:
            call.disconnected.set()
            raise
        except Exception as e:
            log.exception("api tunnel request failed", extra={"path": path})
            await self._send(conn, ApiEnd(id=req.id, error=f"{type(e).__name__}: {e}"))

    async def _send(self, conn: ClientConnection, frame: BaseModel) -> None:
        try:
            await conn.ws.send_json(frame.model_dump())
        except (RuntimeError, WebSocketDisconnect):
            pass
