"""The gateway's local HTTP server: the web UI and `/v1/*` relayed to the Core over the tunnel."""

import asyncio
import base64
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from importlib import resources
from pathlib import Path
from urllib.parse import urlparse

import uvicorn
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mensarium import __version__
from mensarium.client.config import ClientConfig, ClientPaths
from mensarium.client.gateway import auth
from mensarium.client.gateway.tunnel import Call, CoreOffline, Tunnel
from mensarium.contracts.gateway import MAX_REQUEST_BODY, REQUEST_HEADERS, ApiEnd, ApiResponse
from mensarium.shared.crypto import load_or_create_private_key

log = logging.getLogger(__name__)
FIRST_FRAME_TIMEOUT_S = 60


class LoginBody(BaseModel):
    token: str


def create_gateway_app(cfg: ClientConfig, paths: ClientPaths, tunnel: Tunnel) -> FastAPI:
    app = FastAPI(title="Mensarium Gateway", version=__version__, docs_url=None, openapi_url=None)
    web_dir = Path(str(resources.files("mensarium.web")))
    app.mount("/static", StaticFiles(directory=web_dir), name="static")
    port = cfg.gateway.port
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}", *cfg.gateway.allowed_hosts}

    @app.middleware("http")
    async def guard(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        host = request.headers.get("host", "")
        if host not in allowed_hosts:
            return JSONResponse({"detail": "host not allowed"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != host:
            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        return await call_next(request)

    def require_login(request: Request) -> None:
        cookie = request.cookies.get(auth.COOKIE) or ""
        if not cookie or not auth.check_token(paths, cookie):
            raise HTTPException(401, "authentication required")

    def set_session(response: Response) -> None:
        response.set_cookie(auth.COOKIE, auth.load_or_create_token(paths), httponly=True, samesite="strict", max_age=30 * 86400)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/sw.js", include_in_schema=False)
    async def service_worker() -> FileResponse:
        return FileResponse(web_dir / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/login", include_in_schema=False)
    async def login_link(link: str = "") -> RedirectResponse:
        response = RedirectResponse("/", status_code=303)
        if link and auth.take_link(paths, link):
            set_session(response)
        return response

    @app.post("/v1/auth/login")
    async def login(body: LoginBody, response: Response) -> dict[str, bool]:
        if not auth.check_token(paths, body.token):
            await asyncio.sleep(1)
            raise HTTPException(401, "invalid token")
        set_session(response)
        return {"ok": True}

    @app.post("/v1/auth/logout")
    async def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(auth.COOKIE)
        return {"ok": True}

    @app.get("/v1/gateway")
    async def gateway_state() -> dict[str, object]:
        return {
            "gateway": True,
            "online": tunnel.online,
            "rejected": tunnel.rejected_reason,
            "target_id": cfg.target_id,
            "client_name": cfg.name,
            "version": __version__,
        }

    @app.api_route("/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
    async def relay(path: str, request: Request) -> Response:
        # the OAuth provider redirects the browser here without the UI cookie; the Core checks the one-time state
        if not (request.method == "GET" and path == "oauth/callback"):
            require_login(request)
        body = await request.body()
        if len(body) > MAX_REQUEST_BODY:
            raise HTTPException(413, "request body too large")
        headers = {k: v for k, v in request.headers.items() if k.lower() in REQUEST_HEADERS}
        target = f"/v1/{path}" + (f"?{request.url.query}" if request.url.query else "")
        try:
            call = await tunnel.open(request.method, target, headers, body)
        except CoreOffline:
            return JSONResponse({"error": "core-offline", "detail": "Core is offline"}, status_code=503)
        try:
            first = await asyncio.wait_for(call.queue.get(), FIRST_FRAME_TIMEOUT_S)
        except TimeoutError:
            await tunnel.cancel(call)
            raise HTTPException(504, "no answer from Core") from None
        if isinstance(first, ApiEnd):
            if first.error == "core-offline":
                return JSONResponse({"error": "core-offline", "detail": "Core is offline"}, status_code=503)
            raise HTTPException(502, first.error or "Core closed the request")
        if not isinstance(first, ApiResponse):
            await tunnel.cancel(call)
            raise HTTPException(502, "unexpected frame from Core")
        if not first.stream:
            return Response(base64.b64decode(first.body), status_code=first.status, headers=first.headers)
        return StreamingResponse(_stream(tunnel, call, first), status_code=first.status, headers=first.headers)

    return app


async def _stream(tunnel: Tunnel, call: Call, first: ApiResponse) -> AsyncIterator[bytes]:
    try:
        yield base64.b64decode(first.body)
        while True:
            frame = await call.queue.get()
            if isinstance(frame, ApiEnd):
                return
            yield base64.b64decode(frame.body)
    finally:
        await tunnel.cancel(call)


async def run_gateway(cfg: ClientConfig, paths: ClientPaths, key: Ed25519PrivateKey | None = None) -> None:
    key = key or load_or_create_private_key(paths.key)
    tunnel = Tunnel(cfg, paths, key)
    app = create_gateway_app(cfg, paths, tunnel)
    config = uvicorn.Config(app, host=cfg.gateway.host, port=cfg.gateway.port, log_config=None)
    server = uvicorn.Server(config)
    tunnel_task = asyncio.create_task(tunnel.run_forever())
    try:
        await server.serve()
    finally:
        tunnel_task.cancel()
