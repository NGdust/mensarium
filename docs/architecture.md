# Architecture

How Mensarium is put together: the three roles and the boundary between them, what runs inside Core, the wire protocol between Core and a client, and the source layout.

<img src="../landing/shots/architecture.png" alt="Core in the middle, tasks from the browser and Telegram, signed requests to the machines" width="100%">

## The three roles

- **Core** — the agent's brain. It talks to the LLM, builds context, evaluates policy, waits for approvals, and serves the web UI. Core never executes tools itself except through the same signed-request path it uses for any other device (see [Core as a device](#core-as-a-device) below).
- **LLM** — only proposes an action, in a strict schema (`final` or a tool call). It never sees secret values, never talks to a client directly, and cannot name its own target, risk or scope: Core computes those.
- **Client** — a Python asyncio process with no LLM. It holds an outgoing WebSocket to Core, opens no inbound ports, and executes only signed `execution.request` frames it can verify. Two independent sub-roles run inside it: **worker** (executes tools) and **gateway** (serves the web UI on that machine and tunnels browser requests to Core). Either can be enabled without the other.

```
                       ┌────────────────────────── Core ──────────────────────────┐
                       │                                                          │
  Browser ───HTTP/WS──▶│  FastAPI app (app.py)                                    │
  Telegram ───polls───▶│    │                                                     │
                       │    ▼                                                     │
                       │  Orchestrator (asyncio agent loop per task)              │
                       │    │        │                    │                       │
                       │    ▼        ▼                    ▼                       │
                       │  LLM provider   Policy engine   SQLite (aiosqlite)       │
                       │    (router)     (risk/approval)    │                     │
                       │                                    ▼                     │
                       │                                 Event bus (asyncio)      │
                       │                                                          │
                       │  Client hub (ClientHub) ── signed execution.request ──┐  │
                       │  API tunnel (ApiTunnel) ── api.* frames ─────────────┐│  │
                       │  Built-in device (core/device.py) ──────────────────┼┤  │
                       └──────────────────────────────────────────────────────┼┼──┘
                                                      outgoing WSS             ││
                        ┌───────────────────────────────────────────┐         ││
                        │ Client (another machine)                  │◀────────┘│
                        │  worker: ClientAgent — runs tools          │          │
                        │  gateway: local HTTP + web UI, tunnels ────┼──────────┘
                        │           browser requests to Core         │
                        └───────────────────────────────────────────┘
```

## Tool call flow

```
LLM proposal → schema validation → device capability check → policy evaluation
→ risk classification → approval (if required) → signed execution.request → client execution
→ signed execution.result → artifact storage → observation added to context → next step
```

`target_id`, allowed roots, risk and scope are all computed by Core from its own config and the active [profile](../src/agent_core/profile.py); none of it is taken from the model's output.

## Task state machine

Task status values (`TERMINAL_STATUSES` in [src/core/repo.py](../src/core/repo.py)) and the transitions driven by the orchestrator:

```
NEW → VALIDATING → PLANNING → WAITING_APPROVAL → EXECUTING → OBSERVING → PLANNING | SUCCEEDED
                                                                        ↘ FAILED
any non-terminal state → CANCELED (user cancel) | PAUSED (user pause, target offline, Core restart)
PLANNING → FAILED_RECOVERABLE (internal or LLM-call error, resumable)
```

Terminal statuses: `SUCCEEDED`, `FAILED`, `FAILED_RECOVERABLE`, `CANCELED`, `PAUSED`, `IDLE` (`IDLE` is a chat created without a first message yet, or a project chat waiting for its workspace to be prepared). On Core startup, every task that was still active is moved to `PAUSED` with reason `core restarted` — it does not resume on its own; resuming is a user action (`POST /v1/tasks/{id}/resume`).

## Core internals

Core is one FastAPI application ([src/core/app.py](../src/core/app.py)) plus an in-process orchestrator — there is no separate worker process or external queue:

- **FastAPI app** (`core/app.py`) — REST and WebSocket routes, auth (browser session cookie or a gateway-tunneled request), static file serving for the web UI (mounted at `/static`, plus `/sw.js` for the service worker).
- **Orchestrator** (`core/orchestrator.py`) — one `asyncio` task per running agent loop (a chat, or a sub-agent spawned from one). It builds the LLM context, calls the provider, runs the tool-call flow above, and writes each step to the database. Sub-agents run their own loop with the same profile, device, mode and model as their parent, mirrored into the parent's event stream as `agent.event`.
- **Database** (`core/db.py`) — SQLite through `aiosqlite`, one file under `~/.mensarium/core`. Schema is created and migrated in-process on startup (`SCHEMA_VERSION`, `COLUMN_MIGRATIONS`); no separate migration tool.
- **Event bus** (`core/events.py`) — an in-process pub/sub keyed by task id, backed by `asyncio.Queue`. Every stored event also runs through a list of `listeners` (used by push notifications, channels, etc.) and is mirrored to a parent task if the task is a sub-agent.
- **Client hub** (`core/client_hub.py`) — holds the live WebSocket connections from clients, keyed by target id, with separate tracking for `worker` and `gateway` sessions of the same client. It signs and sends `execution.request`/`execution.cancel`/`target.update`/`target.plugins` frames and resolves the futures waiting on their signed responses; it raises `TargetUnavailable` when a device is offline or doesn't answer in time.
- **API tunnel** (`core/api_tunnel.py`) — serves `api.request` frames coming from a gateway session by calling Core's own ASGI app in-process (no network hop), injecting a `mensarium.gateway` scope key so the `auth()` dependency accepts the request without a browser cookie.
- **Built-in device** (`core/device.py`) — the Core host is always a device of itself. It runs an ordinary `ClientAgent` inside the Core process, connected to Core's own port over loopback with the same signed-frame protocol as a remote client (`core/device` holds its own key and pairing, separate from any real client paired later).

## Client protocol

A client connects outward with a WebSocket (`ws_url` from pairing, `/v1/clients/ws`) and never opens a listening port. The handshake and every subsequent request are framed as typed messages (Pydantic models in [src/contracts/protocol.py](../src/contracts/protocol.py) and [src/contracts/gateway.py](../src/contracts/gateway.py)); the canonical set of frame types, used to generate JSON Schema, is in [src/contracts/schemas.py](../src/contracts/schemas.py):

| Frame | Direction | Purpose |
|---|---|---|
| `target.hello` | client → Core | Handshake: session kind (`worker`/`gateway`/`cli`), device info, `Capabilities`, `TargetPolicy` |
| `auth.challenge` / `auth.response` | Core → client → Core | Nonce signed with the client's Ed25519 key |
| `target.heartbeat` | client → Core | Keepalive |
| `execution.request` / `execution.cancel` | Core → client | Signed tool call: nonce, expiry, `policy_snapshot_hash`, tool name and arguments, optional `secrets` |
| `execution.result` | client → Core | Signed result: status, stdout/stderr, artifacts, `target_audit_hash` |
| `target.update` / `target.update.status` | Core → client → Core | Remote update request and its outcome |
| `target.plugins` / `target.plugins.status` | Core → client → Core | MCP servers Core asks the device to run, and their resulting tool lists |
| `core.moved` | Core → client | Core announces it moved to a new address (see [Backup and move](backup-and-move.md)) |
| `core.identity` | Core → client | Answer to `GET /v1/core/identity`: nonce signed with the Core key, used to verify a moved Core |
| `pair.request` / `pair.response` | client → Core | Initial pairing over HTTP, not the WebSocket |

Every `ExecutionRequest` carries `request_id`, `trace_id`, `workspace_id`, `task_id`, `target_id`, a `nonce`, an `expires_at`, and a `policy_snapshot_hash` the client recomputes and compares against its own policy — this is what stops replay and request tampering.

A **gateway** session uses a second frame family, `api.*` (`ApiRequest`/`ApiResponse`/`ApiChunk`/`ApiEnd`/`ApiCancel` in `contracts/gateway.py`), to transport a browser's HTTP request to Core over the same outbound WebSocket: the gateway's local HTTP server wraps the incoming request into an `api.request` frame, Core's `ApiTunnel` runs it against its own ASGI app, and streams the response back as `api.response` plus `api.chunk`/`api.end`. Core never treats anything beyond the HTTP method/path/headers/body from an `api.request` as trusted — it re-runs the same `auth()` dependency it uses for a direct browser request, with the gateway-tunnel scope key standing in for a session cookie.

## LLM provider abstraction

All model calls go through the `LLMProvider` protocol ([src/llm_providers/base.py](../src/llm_providers/base.py)): `list_models`, `chat`, `healthcheck`, `context_window`, plus `name`, `base_url`, `default_model`, `vision_model`. Concrete providers ([src/llm_providers/](../src/llm_providers/)):

- `cli_provider.py` — Claude Code / Codex CLIs already installed on the Core host (no API key needed).
- `openai_compat.py` — any OpenAI-compatible HTTP endpoint: Ollama, llama.cpp, LM Studio, OpenAI, OpenRouter, etc.
- `local_cli.py` — finds the Claude Code and Codex CLIs on the Core host and speaks Codex's app-server protocol for `cli_provider.py`.
- `factory.py` — the table of provider kinds with their defaults, and building a provider from config.
- `router.py` — picks the active provider from config and exposes it to the orchestrator.

Switching providers is a config change; contracts, policy, the client and the UI are unaffected. Provider, model and token usage are recorded per task step.

## Source layout (`src/`)

One Python package (`mensarium`), no monorepo split:

| Subpackage | Contents |
|---|---|
| `agent_core/` | Task state actions, LLM context/prompt building, agent profiles |
| `channels/` | Telegram bot client and Markdown→HTML formatting |
| `cli/` | Typer CLI: `main.py` plus per-area modules (backup, plugins, projects, secrets, skills, automations, service, wizard, update, ui) |
| `client/` | The client process: `agent.py` (worker), `tools.py`, `desktop.py`, `mcp_host.py`, `pairing.py`, `config.py`, `projects.py`, `moving.py` (following a moved Core), `gateway/` (tunnel, server, auth), `macos/` |
| `contracts/` | Pydantic models that are the source of truth for every message and tool argument, plus JSON Schema export |
| `core/` | The Core server: FastAPI app, orchestrator, db, event bus, client hub, API tunnel, device, and one module per feature area (projects, plugins, skills, secrets, channels, automations, push, instructions, memory, oauth, pairing, mirror, ...) |
| `instructions/` | Built-in default `AGENTS.md`/`SOUL.md`/`IDENTITY.md`/`USER.md` templates |
| `llm_providers/` | The `LLMProvider` protocol and its implementations |
| `plugins/` | Built-in plugin/tool implementations (e.g. Google, generic builtins) and the plugin catalog |
| `policy_engine/` | Risk classification and approval decisions for tool calls |
| `profiles/` | Built-in agent profile definitions |
| `shared/` | Cross-cutting helpers: paths, crypto, ids, redaction, cron, bundles, timeutil, logging, toolargs, secret references, versions |
| `skills/` | Agent Skills loading (`SKILL.md` format) and the built-in skills catalog |
| `tool_runtime/` | The tool registry (device tools, Core tools, plan/agent/automation/secret tool definitions) and MCP client code |
| `web/` | The static vanilla JS/CSS UI, served by both Core and a client's gateway |

## JSON Schemas

`make schemas` (`mensarium.contracts.schemas.export`) writes one `<frame-or-tool>.schema.json` file per contract model — every protocol frame in the table above, `llm.chat_request`/`llm.model_response`, `plugin.manifest`, and every `tool.<name>` argument schema — into a `schemas/` directory. Any change to a `contracts/` model should be re-exported and reviewed alongside its contract test.

## Deliberate design choices

- **SQLite + an in-process `asyncio` agent loop, not Postgres/Redis/Dramatiq.** The project ships as one binary with one `install.sh` and no Docker; a separate queue and broker would mean separate services to install, configure and keep alive for a single-user, single-Core deployment.
- **No Docker.** The installer sets up `uv`, Python 3.12 and the package directly under `~/.mensarium`; there is nothing to containerize on either the Core host or a client machine (clients need real OS access — files, shell, screen — that a container would only get in the way of).
- **Vanilla JS UI, served by Core itself (and by a client's gateway).** The UI is static files with no build step, so Core (and the gateway, which needs to serve the same UI on a client machine and tunnel it back) can serve it directly with no Next.js server, bundler or separate deploy artifact.
