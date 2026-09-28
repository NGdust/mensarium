import asyncio
import hmac
import json
import re
import secrets
import shlex
import shutil
import time
from collections import deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote, urlparse

import yaml
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from mensarium import __version__
from mensarium.agent_core.context import INSTRUCTION_FILE_CHARS, context_usage
from mensarium.agent_core.profile import AgentProfile, builtin_profiles
from mensarium.client.agent import ClientAgent
from mensarium.client.gateway import auth as ui_auth
from mensarium.contracts.automations import AutomationCreate, AutomationError, AutomationPatch, Schedule
from mensarium.contracts.gateway import GATEWAY_SCOPE_KEY
from mensarium.contracts.plugins import Plugin
from mensarium.contracts.projects import BrowseBody, ProjectCreate, ProjectError, ProjectPatch
from mensarium.contracts.protocol import AccessMode, PairRequest, PairResponse
from mensarium.contracts.skills import OS, SkillError, SkillMeta, SkillRequires
from mensarium.core import distribution, pairing
from mensarium.core.api_tunnel import ApiTunnel
from mensarium.core.attachments import MAX_FILE_BYTES, MAX_FILES, AttachmentError
from mensarium.core.automations import AutomationManager
from mensarium.core.catalog import Catalog
from mensarium.core.channels import ChannelError, ChannelManager
from mensarium.core.client_hub import ClientHub, TargetUnavailable
from mensarium.core.config import CoreConfig, CorePaths, load_config, read_secret, write_secret
from mensarium.core.db import Database
from mensarium.core.device import ensure_device
from mensarium.core.dreaming import Dreamer, DreamError
from mensarium.core.events import EventBus
from mensarium.core.instructions import InstructionError, InstructionStore
from mensarium.core.limits import LimitsStore
from mensarium.core.memory import KINDS, Memory, NoteError
from mensarium.core.orchestrator import Orchestrator, TaskError, full_access, missing_tools
from mensarium.core.plugins import PluginError, PluginManager
from mensarium.core.projects import ProjectManager
from mensarium.core.providers import ProviderError, Providers
from mensarium.core.releases import ReleaseError, fetch_latest, spawn_update, updater
from mensarium.core.repo import USAGE_FIELDS, Repo
from mensarium.core.skills import SkillStore
from mensarium.llm_providers.router import ProviderRouter
from mensarium.shared.crypto import fingerprint, load_or_create_private_key, public_key_b64
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import iso_in, now_iso, parse_iso, utcnow
from mensarium.shared.versions import parse_version
from mensarium.tool_runtime.registry import REGISTRY

PAIRING_TTL_S = 600
MODELS_TIMEOUT_S = 20


@dataclass
class Core:
    cfg: CoreConfig
    paths: CorePaths
    db: Database
    repo: Repo
    hub: ClientHub
    bus: EventBus
    orchestrator: Orchestrator
    provider: ProviderRouter
    providers: Providers
    workspace_id: str
    core_public_key: str
    cli_token: str
    pair_failures: deque[float]
    catalog: Catalog
    plugins: PluginManager
    skills: SkillStore
    instructions: InstructionStore
    memory: Memory
    dreamer: Dreamer
    channels: ChannelManager
    automations: AutomationManager
    projects: ProjectManager
    limits: LimitsStore
    device_id: str | None


class LoginBody(BaseModel):
    token: str



class ChannelBody(BaseModel):
    token: str | None = Field(None, max_length=200)
    enabled: bool | None = None
    target_id: str | None = Field(None, max_length=100)
    mode: AccessMode | None = None


class TaskCreate(BaseModel):
    target_id: str
    input: str
    profile_id: str = "coding-agent-v1"
    mode: AccessMode = "ask"
    model: str | None = Field(None, min_length=1, max_length=200)
    provider: str | None = Field(None, min_length=1, max_length=100)
    project_id: str | None = Field(None, max_length=100)
    attachments: list[str] = Field(default_factory=list, max_length=MAX_FILES)
    base: str | None = Field(None, min_length=1, max_length=250)
    branch: str | None = Field(None, min_length=1, max_length=200)
    workspace: bool = True


class RevertBody(BaseModel):
    path: str = Field(min_length=1, max_length=1000)


class ModeBody(BaseModel):
    mode: AccessMode


class ModelBody(BaseModel):
    model: str = Field(min_length=1, max_length=200)
    provider: str | None = Field(None, min_length=1, max_length=100)


class ProviderBody(BaseModel):
    kind: str
    base_url: str = Field(max_length=500)
    default_model: str = Field("", max_length=200)
    api_key: str | None = Field(None, max_length=500)
    timeout_s: int = Field(90, ge=5, le=600)
    max_retries: int = Field(2, ge=0, le=5)
    vision_model: str | None = Field(None, max_length=200)


class LimitsRefreshBody(BaseModel):
    provider_id: str | None = None


class ProviderTestBody(BaseModel):
    kind: str
    base_url: str = Field(max_length=500)
    api_key: str | None = Field(None, max_length=500)
    id: str | None = None


class ToolToggle(BaseModel):
    tool: str
    enabled: bool


class NoteBody(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    body: str = Field("", max_length=20000)
    kind: str = "note"
    tags: list[str] = []
    pinned: bool = False
    importance: int = Field(5, ge=1, le=10)
    link_to: str | None = Field(None, min_length=1, max_length=120)


class CenterBody(BaseModel):
    note_id: str | None = Field(None, max_length=100)
    title: str | None = Field(None, min_length=1, max_length=120)


class NotePatch(BaseModel):
    title: str | None = Field(None, min_length=1, max_length=120)
    body: str | None = Field(None, max_length=20000)
    kind: str | None = None
    tags: list[str] | None = None
    pinned: bool | None = None
    importance: int | None = Field(None, ge=1, le=10)


class DreamSettings(BaseModel):
    dreaming: bool | None = None
    hour: int | None = Field(None, ge=0, le=23)
    min_importance: int | None = Field(None, ge=1, le=10)
    tz: str | None = Field(None, max_length=64)


class InstallBody(BaseModel):
    id: str


class PluginConfigBody(BaseModel):
    values: dict[str, Any] = {}
    secrets: dict[str, str | None] = {}
    placement: str | None = None
    risk: str | None = None
    disabled_tools: list[str] | None = None


class McpBody(BaseModel):
    name: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = None
    url: str | None = None
    env: dict[str, str] = {}
    secret_env: dict[str, str] = {}
    headers: dict[str, str] = {}
    secret_headers: dict[str, str] = {}
    placement: str = "core"
    risk: Literal["read", "execute", "write", "network", "destructive"] = "network"
    description: str = ""


class EnabledBody(BaseModel):
    enabled: bool


class InstructionBody(BaseModel):
    content: str = Field("", max_length=200_000)


class SkillBody(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=1024)
    body: str = Field(min_length=1, max_length=200_000)
    homepage: str | None = Field(None, max_length=500)
    always: bool = False
    os: list[OS] = []
    requires_tools: list[str] = Field([], max_length=50)


class MessageBody(BaseModel):
    input: str
    attachments: list[str] = Field(default_factory=list, max_length=MAX_FILES)


class DecisionBody(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = None
    confirm: bool = False


def _ws_url(public_url: str) -> str:
    return public_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1).rstrip("/") + "/v1/clients/ws"


async def _retire_local_target(repo: Repo, paths: CorePaths) -> None:
    """Pre-0.40 Cores registered their own host as a device; that device is gone, so revoke and clean it up."""
    legacy = paths.root / "local-target"
    config = legacy / "config.yaml"
    if not config.exists():
        return
    legacy_id = (yaml.safe_load(config.read_text()) or {}).get("target_id")
    if legacy_id and await repo.get_target(legacy_id):
        await repo.update_target(legacy_id, {"status": "revoked", "revoked_at": now_iso()})
    shutil.rmtree(legacy, ignore_errors=True)


def create_app(paths: CorePaths | None = None) -> FastAPI:
    paths = paths or CorePaths()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        paths.ensure()
        cfg = load_config(paths)
        cli_token = read_secret(paths, "secret://core-cli-token")
        if not cli_token:
            cli_token = secrets.token_urlsafe(24)
            write_secret(paths, "core-cli-token", cli_token)
        providers = Providers(cfg, paths)
        provider = ProviderRouter(providers.active_client(), providers.client)
        providers.router = provider
        limits = LimitsStore(providers, provider)
        limits.start()
        db = Database(paths.db)
        await db.connect()
        repo = Repo(db)
        workspace_id = await repo.get_or_create_workspace()
        for profile in builtin_profiles():
            await repo.upsert_profile(workspace_id, profile.model_dump())
        await db.execute("UPDATE targets SET status = 'offline' WHERE status = 'online'")
        key = load_or_create_private_key(paths.signing_key)
        hub = ClientHub(repo, key)
        hub.api = ApiTunnel(app)
        bus = EventBus(repo)
        memory = Memory(repo)
        skills = SkillStore(repo, workspace_id, paths.skills)
        instructions = InstructionStore(paths.instructions)
        await skills.adopt_plugins()
        plugins = PluginManager(repo, paths, workspace_id)
        plugins.send_plugins = lambda target_id, servers: hub.request_plugins(target_id, servers, cfg.execution.request_ttl_s)
        plugins.device_tools_supported = lambda target_id: hub.supports(target_id, "mcp.call")
        hub.on_connect = plugins.sync_device
        await plugins.start()
        catalog = Catalog(cfg.plugins.catalog_url)
        orchestrator = Orchestrator(repo, hub, bus, provider, cfg, workspace_id, paths.artifacts, memory, plugins, skills, catalog, instructions)
        device = await ensure_device(repo, paths, cfg, public_key_b64(key), workspace_id)
        projects = ProjectManager(repo, workspace_id, hub, cfg.execution.request_ttl_s)
        projects.device_id = device[0].target_id if device else None
        await projects.start()
        orchestrator.projects = projects
        await orchestrator.recover_after_restart()
        dreamer = Dreamer(repo, memory, provider, cfg, workspace_id)
        await dreamer.recover()
        dream_scheduler = asyncio.create_task(dreamer.run_forever())
        await repo.audit(workspace_id, "core", "core.started", {"version": __version__})
        await _retire_local_target(repo, paths)
        channels = ChannelManager(repo, paths, workspace_id, orchestrator, bus)
        await channels.start()
        automations = AutomationManager(repo, workspace_id, orchestrator, channels, cfg.server.public_url)
        orchestrator.automations = automations
        await automations.start()
        device_agent: asyncio.Task[None] | None = None
        if device:
            # The worker dials the Core's own port, which starts listening once startup is over.
            async def run_device() -> None:
                await asyncio.sleep(1)
                await ClientAgent(device[0], paths.device, device[1]).run_forever()

            device_agent = asyncio.create_task(run_device())
        app.state.core = Core(
            cfg=cfg,
            paths=paths,
            db=db,
            repo=repo,
            hub=hub,
            bus=bus,
            orchestrator=orchestrator,
            provider=provider,
            providers=providers,
            workspace_id=workspace_id,
            core_public_key=public_key_b64(key),
            cli_token=cli_token,
            pair_failures=deque(maxlen=50),
            catalog=catalog,
            plugins=plugins,
            skills=skills,
            instructions=instructions,
            memory=memory,
            dreamer=dreamer,
            channels=channels,
            automations=automations,
            projects=projects,
            limits=limits,
            device_id=device[0].target_id if device else None,
        )
        try:
            yield
        finally:
            if device_agent:
                device_agent.cancel()
            limits.stop()
            await automations.stop()
            await projects.stop()
            await channels.stop()
            for runner in list(orchestrator.runners.values()):
                runner.cancel()
            await plugins.stop()
            dream_scheduler.cancel()
            for dream in list(dreamer.tasks):
                dream.cancel()
            await provider.aclose()
            await db.close()

    app = FastAPI(title="Mensarium Core", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    web_dir = Path(str(resources.files("mensarium.web")))
    app.mount("/static", StaticFiles(directory=web_dir), name="static")

    @app.middleware("http")
    async def same_origin(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        """The browser session is a cookie, so a page from another site must not be able to call the API."""
        origin = request.headers.get("origin")
        if origin and urlparse(origin).netloc != request.headers.get("host", ""):
            return JSONResponse({"detail": "origin not allowed"}, status_code=403)
        return await call_next(request)

    def core(request: Request) -> Core:
        return request.app.state.core  # type: ignore[no-any-return]

    def auth(request: Request) -> Core:
        """A browser logged into the Core's own UI, a paired client's gateway, or the Core-host CLI on loopback."""
        c = core(request)
        if request.scope.get(GATEWAY_SCOPE_KEY):
            return c
        cookie = request.cookies.get(ui_auth.COOKIE)
        if cookie and ui_auth.check_token(c.paths.device, cookie):
            return c
        header = request.headers.get("authorization", "")
        local = request.client is not None and request.client.host in ("127.0.0.1", "::1")
        if local and header.lower().startswith("bearer ") and hmac.compare_digest(header[7:], c.cli_token):
            return c
        raise HTTPException(401, "authentication required")

    def set_session(c: Core, response: Response) -> None:
        response.set_cookie(ui_auth.COOKIE, ui_auth.load_or_create_token(c.paths.device), httponly=True, samesite="strict", max_age=30 * 86400)

    def task_error(e: TaskError) -> HTTPException:
        return HTTPException(404 if "not found" in str(e) else 409, str(e))

    def project_error(e: ProjectError) -> HTTPException:
        return HTTPException(404 if str(e) == "project not found" else 409, str(e))

    # ---- public ---------------------------------------------------------------

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(web_dir / "index.html")

    @app.get("/login", include_in_schema=False)
    async def login_link(request: Request, link: str = "") -> RedirectResponse:
        response = RedirectResponse("/", status_code=303)
        if link and ui_auth.take_link(core(request).paths.device, link):
            set_session(core(request), response)
        return response

    @app.post("/v1/auth/login")
    async def login(body: LoginBody, response: Response, c: Core = Depends(core)) -> dict[str, bool]:
        if not ui_auth.check_token(c.paths.device, body.token):
            await asyncio.sleep(1)
            raise HTTPException(401, "invalid token")
        set_session(c, response)
        return {"ok": True}

    @app.post("/v1/auth/logout")
    async def logout(response: Response) -> dict[str, bool]:
        response.delete_cookie(ui_auth.COOKIE)
        return {"ok": True}

    @app.get("/v1/gateway")
    async def gateway_state(c: Core = Depends(core)) -> dict[str, object]:
        """What the UI asks first: here it is served by the Core itself, whose device is `target_id`."""
        return {"gateway": False, "core": True, "online": True, "target_id": c.device_id, "version": __version__}

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
        target = {
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
        await c.repo.create_target(target)
        await c.repo.audit(
            c.workspace_id, "target", "target.paired", {"target_id": target_id, "name": body.name, "hostname": body.hostname}
        )
        await c.automations.add_device(target)
        return PairResponse(
            target_id=target_id,
            workspace_id=c.workspace_id,
            core_public_key=c.core_public_key,
            core_fingerprint=fingerprint(c.core_public_key),
            ws_url=_ws_url(c.cfg.server.public_url),
        )

    @app.websocket("/v1/clients/ws")
    async def client_ws(ws: WebSocket) -> None:
        await ws.app.state.core.hub.handle(ws)

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
            "provider": {
                "name": c.provider.name,
                "base_url": c.provider.base_url,
                "model": c.provider.default_model,
                "health": health.model_dump(),
            },
        }

    @app.put("/v1/system/model")
    async def set_default_model(body: ModelBody, c: Core = Depends(auth)) -> dict[str, str]:
        pid = body.provider or c.cfg.llm.active_provider
        try:
            c.providers.set_default(pid, body.model)
        except ProviderError as e:
            raise provider_error(e) from e
        await c.repo.audit(c.workspace_id, "user", "llm.default_model", {"provider": pid, "model": body.model})
        return {"provider": pid, "model": body.model}

    def provider_error(e: ProviderError) -> HTTPException:
        return HTTPException(404 if "not found" in str(e) else 409, str(e))

    @app.get("/v1/providers")
    async def list_providers(c: Core = Depends(auth)) -> dict[str, Any]:
        return {**c.providers.view(), "detected": await c.providers.detected()}

    @app.put("/v1/providers/{provider_id}")
    async def save_provider(provider_id: str, body: ProviderBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            c.providers.save(provider_id, **body.model_dump())
        except ProviderError as e:
            raise provider_error(e) from e
        await c.repo.audit(c.workspace_id, "user", "provider.saved", {"id": provider_id, "kind": body.kind, "model": body.default_model})
        return c.providers.view()

    @app.delete("/v1/providers/{provider_id}")
    async def remove_provider(provider_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            c.providers.remove(provider_id)
        except ProviderError as e:
            raise provider_error(e) from e
        await c.repo.audit(c.workspace_id, "user", "provider.removed", {"id": provider_id})
        return c.providers.view()

    @app.get("/v1/limits")
    async def limits_view(c: Core = Depends(auth)) -> dict[str, Any]:
        return c.limits.view()

    @app.post("/v1/limits/refresh")
    async def limits_refresh(body: LimitsRefreshBody, c: Core = Depends(auth)) -> dict[str, Any]:
        if body.provider_id and body.provider_id not in c.cfg.llm.providers:
            raise HTTPException(404, "provider not found")
        await c.limits.refresh(body.provider_id)
        return c.limits.view()

    @app.post("/v1/providers/test")
    async def test_provider(body: ProviderTestBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return {"ok": True, "models": await c.providers.test(body.kind, body.base_url, body.api_key, body.id)}
        except ProviderError as e:
            return {"ok": False, "error": str(e)}

    @app.get("/v1/models")
    async def models(c: Core = Depends(auth)) -> list[dict[str, Any]]:
        """Models of every provider, grouped; a provider that fails to answer comes back with its error."""

        async def group(p: dict[str, Any]) -> dict[str, Any]:
            out = {"provider_id": p["id"], "kind": p["kind"], "title": p["title"], "default_model": p["default_model"], "default": p["active"], "models": [], "error": None}
            try:
                out["models"] = [m.model_dump() for m in await asyncio.wait_for(c.provider.get(p["id"]).list_models(), MODELS_TIMEOUT_S)]
            except Exception as e:
                out["error"] = str(e) or type(e).__name__
            return out

        return list(await asyncio.gather(*(group(p) for p in c.providers.view()["providers"])))

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
            "gateway_online": c.hub.gateway_online(t["id"]),
            "core_host": t["id"] == c.device_id,
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
                "disabled_tools": t.get("disabled_tools") or [],
                "remote_update": bool(caps.get("remote_update")),
                "missing_tools": missing_tools(caps.get("tools", [])),
                "desktop": caps.get("desktop") or {},
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
            "install_command": f"curl -fsSL {url}/install.sh | sh",
            "pair_command": f"mensarium client pair --server {url} --code {code}",
        }

    @app.put("/v1/targets/{target_id}/tools")
    async def toggle_tool(target_id: str, body: ToolToggle, c: Core = Depends(auth)) -> dict[str, Any]:
        t = await c.repo.get_target(target_id)
        if not t or t["status"] == "revoked":
            raise HTTPException(404, "target not found")
        known = set(REGISTRY) | {x["name"] for x in await c.plugins.device_tools(target_id)}
        if body.tool not in known:
            raise HTTPException(422, f"unknown tool {body.tool!r}")
        disabled = set(t.get("disabled_tools") or [])
        if body.enabled:
            disabled.discard(body.tool)
        else:
            disabled.add(body.tool)
        await c.repo.update_target(target_id, {"disabled_tools": sorted(disabled)})
        await c.repo.audit(
            c.workspace_id, "user", "target.tool", {"target_id": target_id, "tool": body.tool, "enabled": body.enabled}
        )
        return target_view(c, {**t, "disabled_tools": sorted(disabled)})

    @app.post("/v1/targets/{target_id}/update")
    async def update_target(target_id: str, c: Core = Depends(auth)) -> dict[str, str]:
        t = await c.repo.get_target(target_id)
        if not t or t["status"] == "revoked":
            raise HTTPException(404, "target not found")
        if target_id == c.device_id:
            raise HTTPException(409, "the Core device is updated together with the Core")
        try:
            status = await c.hub.update_device(t, __version__, c.cfg.execution.request_ttl_s)
        except TargetUnavailable as e:
            raise HTTPException(409, str(e)) from e
        await c.repo.audit(
            c.workspace_id,
            "user",
            "target.update",
            {"target_id": target_id, "from": t["agent_version"], "to": __version__, "status": status.status, "reason": status.detail or None},
        )
        if status.status != "started":
            raise HTTPException(409, status.detail or f"update {status.status}")
        return {"status": status.status, "version": __version__}

    @app.get("/v1/system/update")
    async def core_update_info(c: Core = Depends(auth)) -> dict[str, Any]:
        info: dict[str, Any] = {"current": __version__, "latest": None, "available": False, "self_update": updater() is not None}
        try:
            latest = (await fetch_latest(c.cfg.update_url))["version"]
        except ReleaseError as e:
            return info | {"error": str(e)}
        return info | {"latest": latest, "available": parse_version(latest) > parse_version(__version__)}

    @app.post("/v1/system/update")
    async def core_update(c: Core = Depends(auth)) -> dict[str, str]:
        script = updater()
        if script is None:
            raise HTTPException(409, "this Core runs from a source checkout; update it with git")
        try:
            latest = (await fetch_latest(c.cfg.update_url))["version"]
        except ReleaseError as e:
            raise HTTPException(502, str(e)) from e
        if parse_version(latest) <= parse_version(__version__):
            raise HTTPException(409, f"version {__version__} is already the latest")
        await c.repo.audit(c.workspace_id, "user", "core.update", {"from": __version__, "to": latest})
        spawn_update(script, c.cfg.update_url)
        return {"status": "started", "version": latest}

    @app.post("/v1/targets/{target_id}/revoke")
    async def revoke_target(target_id: str, c: Core = Depends(auth)) -> dict[str, bool]:
        if not await c.repo.get_target(target_id):
            raise HTTPException(404, "target not found")
        if target_id == c.device_id:
            raise HTTPException(409, "the Core device cannot be revoked; disable it in the Core config")
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

    def plugin_error(e: PluginError) -> HTTPException:
        return HTTPException(404 if "not installed" in str(e) else 409, str(e))

    async def targets_by_key(c: Core) -> dict[str, dict[str, Any]]:
        rows = [t for t in await c.repo.list_targets() if t["status"] != "revoked"]
        return {**{t["name"]: t for t in rows}, **{t["id"]: t for t in rows}}

    async def plugin_view(c: Core, plugin_id: str) -> dict[str, Any]:
        catalog, _ = await c.catalog.load()
        for item in await c.plugins.listing(catalog):
            if item["id"] == plugin_id:
                return item
        raise HTTPException(404, f"plugin {plugin_id!r} not found")

    @app.get("/v1/plugins")
    async def list_plugins(c: Core = Depends(auth)) -> dict[str, Any]:
        catalog, error = await c.catalog.load()
        devices = [
            {"id": t["id"], "name": t["name"], "online": c.hub.is_online(t["id"]), "plugins": c.hub.supports(t["id"], "mcp.call")}
            for t in await c.repo.list_targets()
            if t["status"] != "revoked"
        ]
        return {"items": await c.plugins.listing(catalog), "error": error, "devices": devices}

    @app.get("/v1/plugins/{plugin_id}")
    async def get_plugin(plugin_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        return await plugin_view(c, plugin_id)

    @app.post("/v1/plugins")
    async def install_plugin(body: InstallBody, c: Core = Depends(auth)) -> dict[str, Any]:
        catalog, _ = await c.catalog.load()
        plugin = catalog.get(body.id)
        if plugin is None:
            raise HTTPException(404, f"plugin {body.id!r} is not in the catalog")
        row = await c.repo.get_plugin(body.id)
        if row and row["source"] == "custom":
            raise HTTPException(409, f"a custom plugin {body.id!r} is installed; remove it first")
        try:
            await c.plugins.install(plugin, "catalog")
        except PluginError as e:
            raise plugin_error(e) from e
        return await plugin_view(c, body.id)

    @app.post("/v1/plugins/custom")
    async def install_custom_plugin(request: Request, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            plugin = Plugin.model_validate(yaml.safe_load(await request.body()))
        except (yaml.YAMLError, ValidationError) as e:
            raise HTTPException(422, f"invalid plugin: {e}") from e
        catalog, _ = await c.catalog.load()
        if plugin.id in catalog:
            raise HTTPException(409, f"id {plugin.id!r} belongs to a catalog plugin; pick another id")
        try:
            await c.plugins.install(plugin, "custom")
        except PluginError as e:
            raise plugin_error(e) from e
        return await plugin_view(c, plugin.id)

    @app.post("/v1/plugins/mcp")
    async def add_mcp_server(body: McpBody, c: Core = Depends(auth)) -> dict[str, Any]:
        """A custom MCP server becomes a custom plugin; its secret env vars and headers become secret settings."""
        plugin_id = f"mcp-{body.name}"
        existing = await c.repo.get_plugin(plugin_id)
        if existing and existing["source"] != "custom":
            raise HTTPException(409, f"{plugin_id} is a catalog plugin; configure it instead")
        config: dict[str, Any] = {}
        secrets: dict[str, str | None] = {}
        template: dict[str, Any] = {"transport": body.transport, "env": dict(body.env), "headers": dict(body.headers), "risk": body.risk}
        for part, values in (("env", body.secret_env), ("headers", body.secret_headers)):
            for key, value in values.items():
                field = f"{part}_{re.sub(r'[^a-z0-9_]', '_', key.lower())}"
                config[field] = {"secret": True, "required": True, "title": key}
                template[part][key] = "{" + field + "}"
                secrets[field] = value
        if body.transport == "stdio":
            try:
                argv = shlex.split(body.command or "")
            except ValueError as e:
                raise HTTPException(422, f"cannot parse the command: {e}") from e
            if not argv:
                raise HTTPException(422, "command is required for a stdio server")
            template |= {"command": argv[0], "args": argv[1:]}
        else:
            template["url"] = body.url
        summary = body.description or f"MCP server {body.name}"
        manifest = {"id": plugin_id, "name": body.name, "version": "1.0.0", "author": "you", "summary": summary, "config": config, "mcp": template}
        targets = await targets_by_key(c)
        placement = "core" if body.placement == "core" else (targets.get(body.placement) or {}).get("id")
        if placement is None:
            raise HTTPException(409, f"unknown device {body.placement!r}")
        if placement != "core" and secrets:
            raise HTTPException(409, "secrets stay in the Core: an MCP server with secret values can run only in the Core")
        try:
            await c.plugins.install(Plugin.model_validate(manifest), "custom")
            await c.plugins.configure(plugin_id, secrets=secrets, placement=placement, risk=body.risk, targets=targets)
        except ValidationError as e:
            raise HTTPException(422, f"invalid MCP server: {e.errors(include_url=False)}") from e
        except PluginError as e:
            raise plugin_error(e) from e
        return await plugin_view(c, plugin_id)

    @app.patch("/v1/plugins/{plugin_id}")
    async def toggle_plugin(plugin_id: str, body: EnabledBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            await c.plugins.set_enabled(plugin_id, body.enabled)
        except PluginError as e:
            raise plugin_error(e) from e
        return await plugin_view(c, plugin_id)

    @app.put("/v1/plugins/{plugin_id}/config")
    async def configure_plugin(plugin_id: str, body: PluginConfigBody, c: Core = Depends(auth)) -> dict[str, Any]:
        targets = await targets_by_key(c)
        placement = body.placement
        if placement and placement != "core":
            placement = (targets.get(placement) or {}).get("id", placement)
        try:
            await c.plugins.configure(
                plugin_id, body.values, body.secrets, placement, body.risk, body.disabled_tools, targets=targets
            )
        except PluginError as e:
            raise plugin_error(e) from e
        return await plugin_view(c, plugin_id)

    @app.post("/v1/plugins/{plugin_id}/update")
    async def update_plugin(plugin_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        return await install_plugin(InstallBody(id=plugin_id), c)

    @app.post("/v1/plugins/{plugin_id}/probe")
    async def probe_plugin(plugin_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            await c.plugins.probe(plugin_id)
        except PluginError as e:
            raise plugin_error(e) from e
        return await plugin_view(c, plugin_id)

    @app.delete("/v1/plugins/{plugin_id}")
    async def remove_plugin(plugin_id: str, c: Core = Depends(auth)) -> dict[str, bool]:
        try:
            await c.plugins.remove(plugin_id)
        except PluginError as e:
            raise plugin_error(e) from e
        return {"ok": True}

    @app.get("/v1/targets/{target_id}/plugin-tools")
    async def target_plugin_tools(target_id: str, c: Core = Depends(auth)) -> list[dict[str, Any]]:
        return await c.plugins.device_tools(target_id)

    async def device_choices(c: Core) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        for t in await c.repo.list_targets():
            if t["status"] == "revoked":
                continue
            hello = c.hub.hello(t["id"])
            devices.append(
                {
                    "id": t["id"],
                    "name": t["name"],
                    "online": c.hub.is_online(t["id"]),
                    "full_access": full_access(t) == "allowed",
                    "projects": bool(hello and hello.capabilities.projects),
                }
            )
        return devices

    @app.get("/v1/channels")
    async def list_channels(c: Core = Depends(auth)) -> dict[str, Any]:
        return {"items": [await c.channels.view()], "devices": await device_choices(c)}

    @app.put("/v1/channels/telegram")
    async def configure_telegram(body: ChannelBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.channels.configure(body.token, body.enabled, body.target_id, body.mode)
        except ChannelError as e:
            raise HTTPException(422, str(e)) from e

    @app.post("/v1/channels/telegram/unbind")
    async def unbind_telegram(c: Core = Depends(auth)) -> dict[str, Any]:
        return await c.channels.unbind()

    @app.delete("/v1/channels/telegram")
    async def remove_telegram(c: Core = Depends(auth)) -> dict[str, bool]:
        await c.channels.remove()
        return {"ok": True}

    def automation_error(e: AutomationError) -> HTTPException:
        return HTTPException(e.code, str(e))

    @app.get("/v1/automations")
    async def list_automations(c: Core = Depends(auth)) -> dict[str, Any]:
        return {
            "items": await c.automations.all(),
            "devices": await device_choices(c),
            "telegram_ready": bool(c.channels.telegram and c.channels.telegram.chat_id),
        }

    @app.post("/v1/automations/preview")
    async def preview_automation(body: Schedule, c: Core = Depends(auth)) -> dict[str, list[str]]:
        return {"next": c.automations.preview(body)}

    @app.post("/v1/automations")
    async def create_automation(body: AutomationCreate, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.automations.create(body)
        except AutomationError as e:
            raise automation_error(e) from e

    @app.get("/v1/automations/{automation_id}")
    async def get_automation(automation_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            view = await c.automations.get(automation_id)
        except AutomationError as e:
            raise automation_error(e) from e
        return {**view, "runs": await c.automations.runs(automation_id)}

    @app.put("/v1/automations/{automation_id}")
    async def update_automation(automation_id: str, body: AutomationPatch, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.automations.update(automation_id, body)
        except AutomationError as e:
            raise automation_error(e) from e

    @app.delete("/v1/automations/{automation_id}")
    async def delete_automation(automation_id: str, c: Core = Depends(auth)) -> dict[str, bool]:
        try:
            await c.automations.delete(automation_id)
        except AutomationError as e:
            raise automation_error(e) from e
        return {"ok": True}

    @app.post("/v1/automations/{automation_id}/run")
    async def run_automation(automation_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.automations.run(automation_id)
        except AutomationError as e:
            raise automation_error(e) from e

    @app.post("/v1/automations/{automation_id}/enable")
    async def enable_automation(automation_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.automations.set_enabled(automation_id, True)
        except AutomationError as e:
            raise automation_error(e) from e

    @app.post("/v1/automations/{automation_id}/disable")
    async def disable_automation(automation_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.automations.set_enabled(automation_id, False)
        except AutomationError as e:
            raise automation_error(e) from e

    @app.get("/v1/automations/{automation_id}/runs")
    async def list_automation_runs(automation_id: str, limit: int = 50, c: Core = Depends(auth)) -> list[dict[str, Any]]:
        return await c.automations.runs(automation_id, min(max(limit, 1), 200))

    def skill_error(e: SkillError) -> HTTPException:
        return HTTPException(404 if "not found" in str(e) else 422, str(e))

    async def skill_view(c: Core, name: str) -> dict[str, Any]:
        try:
            skill = await c.skills.get(name)
        except SkillError as e:
            raise skill_error(e) from e
        return {**skill.view(), "body": skill.body, "text": (skill.path / "SKILL.md").read_text(encoding="utf-8", errors="replace")}

    @app.get("/v1/skills")
    async def list_skills(c: Core = Depends(auth)) -> dict[str, Any]:
        return {"items": [s.view() for s in await c.skills.all()], "folder": str(c.paths.skills)}

    @app.get("/v1/skills/{name}")
    async def get_skill(name: str, c: Core = Depends(auth)) -> dict[str, Any]:
        return await skill_view(c, name)

    async def save_skill(c: Core, name: str, body: SkillBody) -> dict[str, Any]:
        meta = SkillMeta(always=body.always, os=body.os, requires=SkillRequires(tools=[t.strip() for t in body.requires_tools if t.strip()]))
        try:
            skill = await c.skills.save(name, body.description.strip(), body.body, meta, (body.homepage or "").strip() or None)
        except SkillError as e:
            raise skill_error(e) from e
        return await skill_view(c, skill.name)

    @app.post("/v1/skills")
    async def create_skill(body: SkillBody, c: Core = Depends(auth)) -> dict[str, Any]:
        if not body.name:
            raise HTTPException(422, "name is required")
        if (c.paths.skills / body.name / "SKILL.md").is_file():
            raise HTTPException(409, f"you already have a skill named {body.name!r}")
        return await save_skill(c, body.name, body)

    @app.post("/v1/skills/file")
    async def import_skill(request: Request, c: Core = Depends(auth)) -> dict[str, Any]:
        """A whole SKILL.md as text/plain; the name comes from its frontmatter."""
        try:
            skill = await c.skills.save_text((await request.body()).decode("utf-8", errors="replace"))
        except SkillError as e:
            raise skill_error(e) from e
        return await skill_view(c, skill.name)

    @app.put("/v1/skills/{name}")
    async def update_skill(name: str, body: SkillBody, c: Core = Depends(auth)) -> dict[str, Any]:
        """Saving a bundled skill writes your own copy, which is used instead of the bundled one."""
        await skill_view(c, name)
        return await save_skill(c, name, body)

    @app.patch("/v1/skills/{name}")
    async def toggle_skill(name: str, body: EnabledBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            await c.skills.set_enabled(name, body.enabled)
        except SkillError as e:
            raise skill_error(e) from e
        return await skill_view(c, name)

    @app.delete("/v1/skills/{name}")
    async def delete_skill(name: str, c: Core = Depends(auth)) -> dict[str, bool]:
        try:
            await c.skills.delete(name)
        except SkillError as e:
            raise skill_error(e) from e
        return {"ok": True}

    @app.get("/v1/instructions")
    async def list_instructions(c: Core = Depends(auth)) -> dict[str, Any]:
        return {"items": c.instructions.all(), "folder": str(c.paths.instructions), "limit": INSTRUCTION_FILE_CHARS}

    @app.put("/v1/instructions/{name}")
    async def save_instruction(name: str, body: InstructionBody, c: Core = Depends(auth)) -> dict[str, Any]:
        """Empty content removes the file."""
        try:
            return c.instructions.save(name, body.content)
        except InstructionError as e:
            raise HTTPException(404, str(e)) from e

    def note_error(e: NoteError) -> HTTPException:
        return HTTPException(404 if "not found" in str(e) else 409, str(e))

    @app.get("/v1/memory/notes")
    async def list_notes(q: str = "", c: Core = Depends(auth)) -> dict[str, Any]:
        rows = await c.memory.search(q, 500) if q.strip() else await c.repo.list_notes()
        center = await c.memory.center()
        return {"notes": [Memory.view(r) for r in rows], "kinds": list(KINDS), "center": center["id"] if center else None}

    @app.get("/v1/memory/notes/{note_id}")
    async def get_note(note_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        row = await c.repo.get_note(note_id)
        if not row:
            raise HTTPException(404, "note not found")
        return Memory.view(row, full=True) | {"backlinks": await c.memory.backlinks(row["title"])}

    @app.post("/v1/memory/notes")
    async def create_note(body: NoteBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            row = await c.memory.create(**body.model_dump())
        except NoteError as e:
            raise note_error(e) from e
        await c.repo.audit(c.workspace_id, "user", "memory.note_created", {"note_id": row["id"], "title": row["title"]})
        return Memory.view(row, full=True)

    @app.patch("/v1/memory/notes/{note_id}")
    async def update_note(note_id: str, body: NotePatch, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            row = await c.memory.update(note_id, body.model_dump(exclude_none=True))
        except NoteError as e:
            raise note_error(e) from e
        await c.repo.audit(c.workspace_id, "user", "memory.note_updated", {"note_id": note_id, "title": row["title"]})
        return Memory.view(row, full=True)

    @app.delete("/v1/memory/notes/{note_id}")
    async def delete_note(note_id: str, c: Core = Depends(auth)) -> dict[str, bool]:
        row = await c.repo.get_note(note_id)
        if not row:
            raise HTTPException(404, "note not found")
        center = await c.memory.center()
        if center and center["id"] == note_id:
            raise HTTPException(409, "the central note can't be deleted; make another note central first")
        await c.repo.delete_note(note_id)
        await c.repo.audit(c.workspace_id, "user", "memory.note_deleted", {"note_id": note_id, "title": row["title"]})
        return {"ok": True}

    @app.get("/v1/memory/graph")
    async def memory_graph(tags: bool = False, c: Core = Depends(auth)) -> dict[str, Any]:
        return await c.memory.graph(tags)

    @app.post("/v1/memory/center")
    async def memory_center(body: CenterBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            row = await c.memory.set_center(body.note_id) if body.note_id else await c.memory.ensure_center(body.title or "About me")
        except NoteError as e:
            raise note_error(e) from e
        await c.repo.audit(c.workspace_id, "user", "memory.center_set", {"note_id": row["id"], "title": row["title"]})
        return Memory.view(row)

    @app.get("/v1/memory/dreams")
    async def dreams(c: Core = Depends(auth)) -> dict[str, Any]:
        return {"settings": await c.dreamer.settings(), "running": c.dreamer.running, "runs": await c.repo.list_dreams()}

    @app.put("/v1/memory/dreams/settings")
    async def dream_settings(body: DreamSettings, c: Core = Depends(auth)) -> dict[str, Any]:
        settings = await c.dreamer.save_settings(body.model_dump(exclude_none=True))
        await c.repo.audit(c.workspace_id, "user", "memory.dream_settings", settings)
        return settings

    @app.post("/v1/memory/dreams")
    async def start_dream(c: Core = Depends(auth)) -> dict[str, str]:
        try:
            run_id = await c.dreamer.start("manual")
        except DreamError as e:
            raise HTTPException(409, str(e)) from e
        await c.repo.audit(c.workspace_id, "user", "memory.dream_started", {"run_id": run_id})
        return {"id": run_id}

    def task_view(t: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "id", "profile_id", "target_id", "target_name", "input", "status", "status_reason", "result", "mode", "model", "provider", "parent_id", "label",
            "automation_id", "project_id", "branch", "base_ref", "base_sha", "head_sha", "diff_stat",
        )
        return {k: t.get(k) for k in keys} | {"plan": t.get("plan") or [], "created_at": t["created_at"], "updated_at": t["updated_at"]}

    @app.get("/v1/projects")
    async def list_projects(c: Core = Depends(auth)) -> dict[str, Any]:
        return {"items": await c.projects.all(), "devices": await device_choices(c)}

    @app.post("/v1/projects/browse")
    async def browse_project_source(body: BrowseBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.projects.browse(body.target_id, body.path)
        except ProjectError as e:
            raise project_error(e) from e

    @app.post("/v1/projects")
    async def create_project(body: ProjectCreate, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.projects.create(body)
        except ProjectError as e:
            raise project_error(e) from e

    @app.get("/v1/projects/{project_id}")
    async def get_project(project_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            p = await c.projects.get(project_id)
        except ProjectError as e:
            raise project_error(e) from e
        return {**c.projects.view(p), "chats": [task_view(t) for t in await c.repo.list_project_tasks(project_id)]}

    @app.get("/v1/projects/{project_id}/docs")
    async def project_docs(project_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.projects.docs(project_id)
        except ProjectError as e:
            raise project_error(e) from e

    @app.get("/v1/projects/{project_id}/branches")
    async def project_branches(project_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.projects.branches(project_id)
        except ProjectError as e:
            raise project_error(e) from e

    @app.put("/v1/projects/{project_id}")
    async def update_project(project_id: str, body: ProjectPatch, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.projects.update(project_id, body)
        except ProjectError as e:
            raise project_error(e) from e

    @app.post("/v1/projects/{project_id}/sync")
    async def sync_project(project_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return await c.projects.sync(project_id)
        except ProjectError as e:
            raise project_error(e) from e

    @app.delete("/v1/projects/{project_id}")
    async def delete_project(project_id: str, remove_shadow: bool = False, c: Core = Depends(auth)) -> dict[str, bool]:
        try:
            await c.orchestrator.delete_project(project_id, remove_shadow)
        except (ProjectError, TaskError) as e:
            raise HTTPException(404 if "not found" in str(e) else 409, str(e)) from e
        return {"ok": True}

    @app.get("/v1/tasks")
    async def list_tasks(c: Core = Depends(auth)) -> list[dict[str, Any]]:
        return [task_view(t) for t in await c.repo.list_tasks()]

    @app.post("/v1/tasks")
    async def create_task(body: TaskCreate, c: Core = Depends(auth)) -> dict[str, Any]:
        if not body.input.strip() and not body.attachments and not body.project_id:
            raise HTTPException(422, "input is empty")
        try:
            return task_view(
                await c.orchestrator.create_task(
                    body.profile_id, body.target_id, body.input.strip(), body.mode, body.model, project_id=body.project_id,
                    provider=body.provider, attachments=body.attachments, base=body.base, branch=body.branch, workspace=body.workspace,
                )
            )
        except TaskError as e:
            raise task_error(e) from e

    @app.get("/v1/tasks/{task_id}/changes")
    async def task_changes(task_id: str, path: str | None = Query(None, min_length=1, max_length=1000), c: Core = Depends(auth)) -> dict[str, Any]:
        task = await c.repo.get_task(task_id)
        if not task:
            raise HTTPException(404, "task not found")
        try:
            return await c.projects.changes(task, path)
        except ProjectError as e:
            raise project_error(e) from e

    @app.get("/v1/tasks/{task_id}")
    async def get_task(task_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        t = await c.repo.get_task(task_id)
        if not t:
            raise HTTPException(404, "task not found")
        return task_view(t)

    @app.get("/v1/tasks/{task_id}/usage")
    async def task_usage(task_id: str, c: Core = Depends(auth)) -> dict[str, Any]:
        if not await c.repo.get_task(task_id):
            raise HTTPException(404, "task not found")
        ids = [task_id] + [t["id"] for t in await c.repo.list_children(task_id)]
        models = await c.repo.usage_by_model(ids)
        step = await c.repo.last_llm_step(task_id)
        context = None
        if step and step["input"].get("context"):
            prompt_tokens = int((step["usage"] or {}).get("prompt_tokens") or 0)
            context = {**context_usage(step["input"]["context"], prompt_tokens), "model": step["model_id"], "provider": step["provider"]}
        return {
            "models": models,
            "total": {k: sum(int(m[k]) for m in models) for k in ("calls", *USAGE_FIELDS)},
            "context": context,
            "agents": len(ids) - 1,
        }

    @app.post("/v1/tasks/{task_id}/changes/revert")
    async def revert_task_file(task_id: str, body: RevertBody, c: Core = Depends(auth)) -> dict[str, bool]:
        try:
            await c.orchestrator.revert_file(task_id, body.path)
        except TaskError as e:
            raise task_error(e) from e
        return {"ok": True}

    @app.post("/v1/tasks/{task_id}/mode")
    async def set_mode(task_id: str, body: ModeBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return task_view(await c.orchestrator.set_mode(task_id, body.mode))
        except TaskError as e:
            raise task_error(e) from e

    @app.post("/v1/tasks/{task_id}/model")
    async def set_task_model(task_id: str, body: ModelBody, c: Core = Depends(auth)) -> dict[str, Any]:
        try:
            return task_view(await c.orchestrator.set_model(task_id, body.model, body.provider))
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
        if not body.input.strip() and not body.attachments:
            raise HTTPException(422, "input is empty")
        try:
            return task_view(await c.orchestrator.post_message(task_id, body.input.strip(), body.attachments))
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
                if (draft := c.bus.drafts.get(task_id)) and draft.sent:
                    yield _sse(draft.snapshot())
                while True:
                    try:
                        ev = await asyncio.wait_for(q.get(), 15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if ev["seq"] is None:
                        yield _sse(ev)
                    elif ev["seq"] > last:
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

    @app.post("/v1/attachments")
    async def upload_attachment(request: Request, name: str = "file", c: Core = Depends(auth)) -> dict[str, Any]:
        """A file for a chat message, sent as the raw body; its type is taken from the bytes, not from the browser."""
        data = await request.body()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f"the file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB")
        try:
            return (await c.orchestrator.attachments.save(name, data)).model_dump(exclude={"text", "truncated"})
        except AttachmentError as e:
            raise HTTPException(415 if "unsupported" in str(e) else 422, str(e)) from e

    @app.get("/v1/artifacts/{artifact_id}")
    async def artifact(artifact_id: str, c: Core = Depends(auth)) -> Response:
        row = await c.repo.get_artifact(artifact_id)
        if not row:
            raise HTTPException(404, "artifact not found")
        nosniff = {"X-Content-Type-Options": "nosniff"}
        if row["kind"] == "upload":
            meta = row["metadata"] if isinstance(row["metadata"], dict) else {}
            path = Path(str(row["uri"]).removeprefix("file://"))
            if path.parent != c.paths.artifacts or not path.exists():
                raise HTTPException(404, "file not found")
            filename = quote(str(meta.get("name") or "file"))
            disposition = "inline" if meta.get("type") == "image" else "attachment"
            return FileResponse(
                path,
                media_type=str(meta.get("mime") or "application/octet-stream"),
                headers={**nosniff, "Content-Disposition": f"{disposition}; filename*=UTF-8''{filename}"},
            )
        for suffix, media in ((".jpg", "image/jpeg"), (".png", "image/png")):
            if (image := c.paths.artifacts / f"{artifact_id}{suffix}").exists():
                return FileResponse(image, media_type=media, headers=nosniff)
        path = c.paths.artifacts / f"{artifact_id}.txt"
        return PlainTextResponse(path.read_text(errors="replace") if path.exists() else "", headers=nosniff)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(c: Core = Depends(auth)) -> PlainTextResponse:
        rows = await c.db.fetchall("SELECT status, COUNT(*) AS n FROM tasks GROUP BY status")
        lines = [f'mensarium_tasks{{status="{r["status"]}"}} {r["n"]}' for r in rows]
        lines.append(f"mensarium_targets_online {len(c.hub.connections)}")
        lines.append(f"mensarium_tasks_running {len(c.orchestrator.runners)}")
        return PlainTextResponse("\n".join(lines) + "\n")

    return app


def _sse(ev: dict[str, Any]) -> str:
    """Live-only events carry no id, so a reconnect resumes after the last stored one."""
    head = f"id: {ev['seq']}\n" if ev["seq"] is not None else ""
    return f"{head}data: {json.dumps(ev, ensure_ascii=False)}\n\n"
