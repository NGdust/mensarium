import asyncio
import hmac
import json
import time
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request, Response, WebSocket
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ValidationError

from mensarium import __version__
from mensarium.agent_core.profile import AgentProfile, builtin_profiles
from mensarium.contracts.protocol import AccessMode, PairRequest, PairResponse
from mensarium.core import distribution, pairing
from mensarium.core.config import CoreConfig, CorePaths, load_config, read_secret
from mensarium.core.db import Database
from mensarium.core.events import EventBus
from mensarium.core.local_target import ensure_local_target, local_target_paths
from mensarium.core.orchestrator import Orchestrator, TaskError, full_access
from mensarium.core.repo import Repo
from mensarium.core.target_hub import TargetHub
from mensarium.llm_providers.factory import build_provider
from mensarium.llm_providers.openai_compat import OpenAICompatibleProvider
from mensarium.shared.crypto import fingerprint, load_or_create_private_key, public_key_b64
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import iso_in, now_iso, parse_iso, utcnow
from mensarium.target.agent import TargetAgent

PAIRING_TTL_S = 600
SESSION_COOKIE = "hd_session"


@dataclass
class Core:
    cfg: CoreConfig
    paths: CorePaths
    db: Database
    repo: Repo
    hub: TargetHub
    bus: EventBus
    orchestrator: Orchestrator
    provider: OpenAICompatibleProvider
    workspace_id: str
    core_public_key: str
    admin_token: str
    pair_failures: deque[float]
    local_target_id: str | None


class LoginBody(BaseModel):
    token: str


class TaskCreate(BaseModel):
    target_id: str
    input: str
    profile_id: str = "coding-agent-v1"
    mode: AccessMode = "ask"


class ModeBody(BaseModel):
    mode: AccessMode


class MessageBody(BaseModel):
    input: str


class DecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None
    confirm: bool = False


def _ws_url(public_url: str) -> str:
    return public_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1).rstrip("/") + "/v1/targets/ws"


def create_app(paths: CorePaths | None = None) -> FastAPI:
    paths = paths or CorePaths()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        paths.ensure()
        cfg = load_config(paths)
        admin_token = read_secret(paths, "secret://admin-token")
        if not admin_token:
            raise RuntimeError("admin token is missing; run `mensarium setup`")
        pcfg = cfg.llm.providers[cfg.llm.active_provider]
        provider = build_provider(
            cfg.llm.active_provider,
            base_url=pcfg.base_url,
            default_model=pcfg.default_model,
            api_key=read_secret(paths, pcfg.api_key_ref),
            timeout_s=pcfg.timeout_s,
            max_retries=pcfg.max_retries,
        )
        db = Database(paths.db)
        await db.connect()
        repo = Repo(db)
        workspace_id = await repo.get_or_create_workspace()
        for profile in builtin_profiles():
            await repo.upsert_profile(workspace_id, profile.model_dump())
        await db.execute("UPDATE targets SET status = 'offline' WHERE status = 'online'")
        key = load_or_create_private_key(paths.signing_key)
        hub = TargetHub(repo, key)
        bus = EventBus(repo)
        orchestrator = Orchestrator(repo, hub, bus, provider, cfg, workspace_id, paths.artifacts)
        await orchestrator.recover_after_restart()
        await repo.audit(workspace_id, "core", "core.started", {"version": __version__})
        local = await ensure_local_target(repo, paths, cfg, public_key_b64(key), workspace_id)
        local_agent = None
        if local:
            local_agent = asyncio.create_task(TargetAgent(local[0], local_target_paths(paths), local[1]).run_forever())
        app.state.core = Core(
            cfg=cfg,
            paths=paths,
            db=db,
            repo=repo,
            hub=hub,
            bus=bus,
            orchestrator=orchestrator,
            provider=provider,
            workspace_id=workspace_id,
            core_public_key=public_key_b64(key),
            admin_token=admin_token,
            pair_failures=deque(maxlen=50),
            local_target_id=local[0].target_id if local else None,
        )
        try:
            yield
        finally:
            for runner in list(orchestrator.runners.values()):
                runner.cancel()
            if local_agent:
                local_agent.cancel()
            await provider.aclose()
            await db.close()

    app = FastAPI(title="Mensarium Core", version=__version__, lifespan=lifespan, docs_url="/docs")
    web_dir = Path(str(resources.files("mensarium.core") / "web"))
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    def core(request: Request) -> Core:
        return request.app.state.core  # type: ignore[no-any-return]

    def auth(request: Request) -> Core:
        c = core(request)
        token = request.cookies.get(SESSION_COOKIE) or ""
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:]
        if not token or not hmac.compare_digest(token, c.admin_token):
            raise HTTPException(401, "authentication required")
        return c

    def task_error(e: TaskError) -> HTTPException:
        return HTTPException(404 if "not found" in str(e) else 409, str(e))

    # ---- public ---------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/install.sh", include_in_schema=False)
    async def install_sh(request: Request) -> PlainTextResponse:
        try:
            return PlainTextResponse(distribution.install_script(core(request).cfg.server.public_url))
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.get("/dist/mensarium.tar.gz", include_in_schema=False)
    async def dist() -> Response:
        try:
            data = await asyncio.to_thread(distribution.source_tarball)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        return Response(data, media_type="application/gzip")

    @app.get("/dist/latest.json", include_in_schema=False)
    async def dist_latest() -> dict[str, str]:
        try:
            return await asyncio.to_thread(distribution.latest_manifest, __version__)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e

    @app.post("/v1/auth/login")
    async def login(body: LoginBody, response: Response, c: Core = Depends(core)) -> dict[str, bool]:
        if not hmac.compare_digest(body.token.strip(), c.admin_token):
            await asyncio.sleep(1)
            raise HTTPException(401, "invalid token")
        response.set_cookie(SESSION_COOKIE, c.admin_token, httponly=True, samesite="strict", max_age=30 * 86400)
        return {"ok": True}

    @app.post("/v1/auth/logout")
    async def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(SESSION_COOKIE)
        return {"ok": True}

    @app.post("/v1/targets/pair")
    async def pair(body: PairRequest, c: Core = Depends(core)) -> PairResponse:
        now = time.monotonic()
        if sum(1 for t in c.pair_failures if now - t < 600) >= 10:
            raise HTTPException(429, "too many failed pairing attempts, try again later")
        row = await c.repo.get_pairing(pairing.code_hash(body.code))
        if not row or row["used_at"] or parse_iso(row["expires_at"]) < utcnow():
            c.pair_failures.append(now)
            await asyncio.sleep(1)
            raise HTTPException(403, "pairing code is invalid, used or expired")
        target_id = new_id("tgt")
        if not await c.repo.use_pairing(row["id"], target_id):
            raise HTTPException(403, "pairing code already used")
        await c.repo.create_target(
            {
                "id": target_id,
                "workspace_id": c.workspace_id,
                "name": body.name[:80],
                "platform": body.platform,
                "hostname": body.hostname,
                "status": "offline",
                "public_key": body.public_key,
                "agent_version": body.agent_version,
                "created_at": now_iso(),
            }
        )
        await c.repo.audit(
            c.workspace_id, "target", "target.paired", {"target_id": target_id, "name": body.name, "hostname": body.hostname}
        )
        return PairResponse(
            target_id=target_id,
            workspace_id=c.workspace_id,
            core_public_key=c.core_public_key,
            core_fingerprint=fingerprint(c.core_public_key),
            ws_url=_ws_url(c.cfg.server.public_url),
        )

    @app.websocket("/v1/targets/ws")
    async def target_ws(ws: WebSocket) -> None:
        await ws.app.state.core.hub.handle(ws)

    # ---- authenticated ----------------------------------------------------------

    @app.get("/v1/system")
    async def system(c: Core = Depends(auth)) -> dict[str, Any]:
        health = await c.provider.healthcheck()
        return {
            "version": __version__,
            "workspace_id": c.workspace_id,
            "public_url": c.cfg.server.public_url,
            "core_key_fingerprint": fingerprint(c.core_public_key),
            "local_target_id": c.local_target_id,
            "provider": {
                "name": c.provider.name,
                "base_url": c.provider.base_url,
                "model": c.provider.default_model,
                "health": health.model_dump(),
            },
        }

    @app.get("/v1/models")
    async def models(c: Core = Depends(auth)) -> list[dict[str, str]]:
        try:
            return [m.model_dump() for m in await c.provider.list_models()]
        except Exception as e:
            raise HTTPException(502, f"provider error: {e}") from e

    def target_view(c: Core, t: dict[str, Any]) -> dict[str, Any]:
        status = t["status"] if t["status"] == "revoked" else ("online" if c.hub.is_online(t["id"]) else "offline")
        caps = t.get("capabilities") or {}
        policy = t.get("policy") or {}
        return {
            "id": t["id"],
            "name": t["name"],
            "platform": t["platform"],
            "hostname": t["hostname"],
            "status": status,
            "last_seen_at": t["last_seen_at"],
            "agent_version": t["agent_version"],
            "created_at": t["created_at"],
            "capabilities": {
                "tools": caps.get("tools", []),
                "shells": caps.get("shells", []),
                "roots": policy.get("roots", []),
                "command_allowlist": policy.get("command_allowlist", []),
                "allow_full_access": policy.get("allow_full_access", False),
                "full_access": full_access(t),
            },
        }

    @app.get("/v1/targets")
    async def list_targets(c: Core = Depends(auth)) -> list[dict[str, Any]]:
        return [target_view(c, t) for t in await c.repo.list_targets()]

    @app.post("/v1/targets/pairing-codes")
    async def create_pairing_code(c: Core = Depends(auth)) -> dict[str, str]:
        code = pairing.generate_code()
        expires = iso_in(PAIRING_TTL_S)
        await c.repo.create_pairing(pairing.code_hash(code), expires)
        await c.repo.audit(c.workspace_id, "user", "pairing.code_created", {"expires_at": expires})
        url = c.cfg.server.public_url.rstrip("/")
        return {
            "code": code,
            "expires_at": expires,
            "install_command": f"curl -fsSL {url}/install.sh | sh -s -- --code {code}",
            "pair_command": f"mensarium target pair --server {url} --code {code}",
        }

    @app.post("/v1/targets/{target_id}/revoke")
    async def revoke_target(target_id: str, c: Core = Depends(auth)) -> dict[str, bool]:
        if not await c.repo.get_target(target_id):
            raise HTTPException(404, "target not found")
        await c.repo.update_target(target_id, {"status": "revoked", "revoked_at": now_iso()})
        await c.hub.disconnect(target_id, "revoked")
        await c.repo.audit(c.workspace_id, "user", "target.revoked", {"target_id": target_id})
        return {"ok": True}

    @app.get("/v1/agent-profiles")
    async def list_profiles(c: Core = Depends(auth)) -> list[dict[str, Any]]:
        out = []
        for row in await c.repo.list_profiles():
            p = AgentProfile.model_validate(row["body"])
            out.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "version": p.version,
                    "allowed_tools": p.allowed_tools,
                    "limits": p.limits.model_dump(),
                    "llm": {"model": p.llm.model or c.provider.default_model, "temperature": p.llm.temperature},
                    "approval": p.approval.model_dump(),
                }
            )
        return out

    @app.post("/v1/agent-profiles")
    async def import_profile(request: Request, c: Core = Depends(auth)) -> dict[str, str]:
        try:
            profile = AgentProfile.model_validate(yaml.safe_load(await request.body()))
        except (yaml.YAMLError, ValidationError) as e:
            raise HTTPException(422, f"invalid profile: {e}") from e
        await c.repo.upsert_profile(c.workspace_id, profile.model_dump())
        await c.repo.audit(c.workspace_id, "user", "profile.imported", {"id": profile.id, "version": profile.version})
        return {"id": profile.id}

    def task_view(t: dict[str, Any]) -> dict[str, Any]:
        keys = ("id", "profile_id", "target_id", "target_name", "input", "status", "status_reason", "result", "mode")
        return {k: t.get(k) for k in keys} | {"created_at": t["created_at"], "updated_at": t["updated_at"]}

    @app.get("/v1/tasks")
    async def list_tasks(c: Core = Depends(auth)) -> list[dict[str, Any]]:
        return [task_view(t) for t in await c.repo.list_tasks()]

    @app.post("/v1/tasks")
    async def create_task(body: TaskCreate, c: Core = Depends(auth)) -> dict[str, Any]:
        if not body.input.strip():
            raise HTTPException(422, "input is empty")
        try:
            return task_view(await c.orchestrator.create_task(body.profile_id, body.target_id, body.input, body.mode))
        except TaskError as e:
            raise task_error(e) from e

    @app.get("/v1/tasks/{task_id}")
    async def get_task(task_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        t = await c.repo.get_task(task_id)
        if not t:
            raise HTTPException(404, "task not found")
        return task_view(t)

    @app.post("/v1/tasks/{task_id}/mode")
    async def set_mode(task_id: str, body: ModeBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return task_view(await c.orchestrator.set_mode(task_id, body.mode))
        except TaskError as e:
            raise task_error(e) from e

    @app.delete("/v1/tasks/{task_id}")
    async def delete_task(task_id: str, c: Core = Depends(auth)) -> dict[str, bool]:
        try:
            await c.orchestrator.delete(task_id)
        except TaskError as e:
            raise task_error(e) from e
        return {"ok": True}

    @app.post("/v1/tasks/{task_id}/messages")
    async def post_message(task_id: str, body: MessageBody, c: Core = Depends(auth)) -> dict[str, Any]:
        if not body.input.strip():
            raise HTTPException(422, "input is empty")
        try:
            return task_view(await c.orchestrator.post_message(task_id, body.input))
        except TaskError as e:
            raise task_error(e) from e

    @app.post("/v1/tasks/{task_id}/{action}")
    async def task_action(task_id: str, action: str, c: Core = Depends(auth)) -> dict[str, Any]:
        handlers = {"cancel": c.orchestrator.cancel, "pause": c.orchestrator.pause, "resume": c.orchestrator.resume}
        if action not in handlers:
            raise HTTPException(404, "unknown action")
        try:
            await c.repo.audit(c.workspace_id, "user", f"task.{action}", {"task_id": task_id})
            return task_view(await handlers[action](task_id))
        except TaskError as e:
            raise task_error(e) from e

    @app.get("/v1/tasks/{task_id}/events")
    async def task_events(task_id: str, request: Request, after: int = 0, c: Core = Depends(auth)) -> StreamingResponse:
        if not await c.repo.get_task(task_id):
            raise HTTPException(404, "task not found")
        last_id = request.headers.get("last-event-id")
        if last_id and last_id.isdigit():
            after = max(after, int(last_id))

        async def stream() -> AsyncIterator[str]:
            q = c.bus.subscribe(task_id)
            last = after
            try:
                for ev in await c.repo.list_events(task_id, after):
                    last = ev["seq"]
                    yield _sse(ev)
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), 15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if ev["seq"] > last:
                        last = ev["seq"]
                        yield _sse(ev)
            finally:
                c.bus.unsubscribe(task_id, q)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    @app.post("/v1/approvals/{approval_id}/decision")
    async def decide(approval_id: str, body: DecisionBody, c: Core = Depends(auth)) -> dict[str, bool]:
        try:
            await c.orchestrator.decide(approval_id, body.decision, body.note, body.confirm)
        except TaskError as e:
            raise task_error(e) from e
        return {"ok": True}

    @app.get("/v1/audit")
    async def audit(limit: int = 200, c: Core = Depends(auth)) -> list[dict[str, Any]]:
        return await c.repo.list_audit(min(limit, 1000))

    @app.get("/v1/artifacts/{artifact_id}")
    async def artifact(artifact_id: str, c: Core = Depends(auth)) -> Response:
        row = await c.repo.get_artifact(artifact_id)
        if not row:
            raise HTTPException(404, "artifact not found")
        path = c.paths.artifacts / f"{artifact_id}.txt"
        return PlainTextResponse(path.read_text(errors="replace") if path.exists() else "")

    @app.get("/metrics", include_in_schema=False)
    async def metrics(c: Core = Depends(auth)) -> PlainTextResponse:
        rows = await c.db.fetchall("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")
        lines = [f'mensarium_tasks{{status="{r["status"]}"}} {r["n"]}' for r in rows]
        lines.append(f"mensarium_targets_online {len(c.hub.connections)}")
        lines.append(f"mensarium_tasks_running {len(c.orchestrator.runners)}")
        return PlainTextResponse("\n".join(lines) + "\n")

    return app


def _sse(ev: dict[str, Any]) -> str:
    return f"id: {ev['seq']}\ndata: {json.dumps(ev, ensure_ascii=False)}\n\n"
