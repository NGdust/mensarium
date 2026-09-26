English · [Русский](README.ru.md)

# Mensarium

A portable agent harness. **Core** calls the LLM, builds context, checks model-proposed actions against policies, waits for user approval, writes an audit trail, and holds all state — SQLite, secrets, Telegram, automations, plugins, skills, memory. It serves its own web UI (log in with a token from `mensarium core token`, or a one-time link from `mensarium core open`) and is itself the first device: a worker runs inside the Core process, attached over loopback with the same signed frames as any remote client, so the agent can work on the Core host without installing anything else there. **Client** is installed on every other machine the agent works on or is controlled from: one ED25519 key, one pairing, and two independent processes — `worker`, which executes signed tool requests, and `gateway`, which serves the web UI on that machine and relays it to Core over its own WebSocket session.

The model never gets direct access to shell, files, network, or secrets: it only proposes a `tool_call`, and Core decides whether it can be executed.

## Installation

```sh
curl -fsSL https://mensarium.com/install.sh | sh
```

This installs [uv](https://docs.astral.sh/uv/) and Python 3.12, the package in `~/.mensarium/venv`, and the `mensarium` command in `~/.local/bin` — no parameters, no Docker. All configuration happens through the command itself.

On the machine that should be the brain (a server or a laptop):

```sh
mensarium core
```

With no subcommand this runs the setup wizard if Core isn't configured yet (port, address, LLM provider and model, service, this machine as a device: name, folders, program allowlist, full access, bash scripts, MCP plugins), or shows Core's state if it already is; `mensarium core setup` reconfigures it. Once it's done you have the web UI and the first device — this machine itself — right away. At the end it prints `mensarium core pair-code` — a one-time code (10 minutes) for pairing clients.

On every other machine the agent should work on or be controlled from:

```sh
mensarium client
```

With no subcommand this runs the client wizard if not paired yet: Core URL, folders, program allowlist, device permissions, the pairing code, then two questions — run the agent's tools here (`worker`) and open the web UI here (`gateway`: port, localhost-only or other machines too). It installs the services and prints a one-time login link; `mensarium client setup` reconfigures it. `mensarium client pair --server URL --code CODE --root DIR` pairs non-interactively and, in a terminal, continues with the worker/gateway questions. Running it on the Core host is refused: "This machine runs the Core and is already its device."

A pairing code is also available from the web UI (Devices → Pair a device), which shows both the install command and the pair command.

Clients only ever talk to Core, never to each other — a star topology:

```
                     ┌──────────────────────────────┐
   Telegram ────────►│ core                         │
   (Core channel)    │  orchestrator, LLM, policy   │
   browser  ────────►│  UI, own device, approvals   │
                     │  sqlite, secrets             │
                     │  cron, WSS /v1/clients, CLI  │
                     └──────┬────────────┬──────────┘
                    WSS     │            │     WSS
              ┌─────────────┘            └──────────────┐
              ▼                                         ▼
 ┌──────────────────────────┐                  ┌──────────────┐
 │ client (laptop)          │                  │ client       │
 │  worker: runs tools      │                  │ (server 2)   │
 │  gateway: 127.0.0.1:8790 │                  │  worker      │
 │   └─ UI + tunnel to core │                  └──────────────┘
 └────────────▲─────────────┘
              │ http://127.0.0.1:8790
         ┌────┴────┐
         │ browser │
         └─────────┘
```

## Commands

| Command | What it does |
|---|---|
| `mensarium core` | Set up the Core (first run) or show its state |
| `mensarium core setup` | Reconfigure the Core |
| `mensarium core serve` | Run Core in the foreground |
| `mensarium core pair-code` | One-time pairing code (10 minutes) |
| `mensarium core open` | Open the web UI with a one-time login link |
| `mensarium core token [--rotate]` | Token for logging into the Core's web UI |
| `mensarium core backup -o file.pab` / `restore file.pab` | Encrypted transfer of Core to another host |
| `mensarium client` | Set up this client (first run) or show its state |
| `mensarium client setup` | Reconfigure: pairing, folders, worker, gateway |
| `mensarium client pair --server URL --code CODE --root DIR` | Pair without the wizard (`--no-full-access`, `--no-remote-update`, `--no-shell` restrict the device) |
| `mensarium client run` | Run the worker in the foreground |
| `mensarium client gateway run` | Run the gateway (web UI) in the foreground |
| `mensarium client gateway open` | Open the web UI with a one-time login link |
| `mensarium client gateway token [--rotate]` | Token for logging into the web UI |
| `mensarium client gateway status` | Gateway state and Core connection |
| `mensarium client permissions` | Ask the OS again for screen recording and accessibility |
| `mensarium client plugins` | MCP servers the Core runs on this device |
| `mensarium status` | What is installed and running |
| `mensarium version` | Version, components on this machine, and available update |
| `mensarium update` | Update: Core from mensarium.com, a client from its own Core (`--check` only checks) |
| `mensarium plugins ...`, `mensarium mcp ...`, `mensarium skills ...`, `mensarium automations ...` | unchanged (run on the Core host) |
| `mensarium service install\|stop\|restart\|logs core\|client\|gateway` | Manage the services |
| `mensarium uninstall --purge` | Remove services and data |

## How it works

```
LLM proposal → schema validation → target capability check → policy evaluation
→ risk classification → approval (if required) → signed request → target execution
→ signed result → artifact → observation added to context → next step
```

- LLM providers: Ollama Cloud, local Ollama, llama.cpp, LM Studio, OpenAI, OpenRouter or any OpenAI-compatible server — all through the OpenAI-compatible API — plus Claude Code and Codex CLI installed on the Core host (found automatically, connected with one click in Settings → Providers or in `mensarium core`; they think through your subscription, their own tools are switched off). They are added, checked and switched in Settings → Providers (or in the `mensarium core` wizard); the active provider changes without a restart and keys stay in Core secrets.
- Access modes per chat: "Ask before acting" (default) and "Full access". The Core host is a device by itself: a worker runs inside the Core process, attached over loopback with the same signed frames as any remote client, so nothing extra needs installing there (settings live in the `device` section of `core/config.yaml`; its key and login token live under `~/.mensarium/core/device/`). On start, a Core that finds a client in the same `~/.mensarium` paired with itself adopts it — device id, key, folders and login token move into Core, the client and gateway services are removed, and `client/` is renamed to `client.adopted`; the device's chats, projects and automations carry over.
- Device tools, all native in the client: read without confirmation (`files.list`, `files.read`, `files.search`, `files.stat`, `files.find`, `git.status`, `git.diff`, `system.info`, `process.list`, `net.ports`), changes with confirmation (`files.write`, `files.edit`, `files.mkdir`, `files.move`, `files.copy`, `net.http`), irreversible ones always confirmed (`files.delete`, `process.kill`), and `shell.bash` for real bash scripts (reviewed and approved per script, `sudo` refused, can be disabled per device with `--no-shell`). `shell.exec` runs one allowlisted program without a shell. Desktop tools appear when the device has the OS utilities: `screen.capture` (a screenshot the model sees as an image; set a "model for images" on the provider, e.g. `gemma4` on Ollama Cloud, and Core switches to it on steps with a screenshot), `screen.windows`, `input.mouse`, `input.type`, `input.key`, `app.open`, `system.volume`. On macOS the worker runs through `~/Applications/Mensarium.app`, so Privacy & Security shows Mensarium (not Python); it asks for Screen Recording and Accessibility after install and after every update (`mensarium client permissions` asks again); mouse moves need `brew install cliclick`.
- The web UI is served by Core itself and by each client's gateway: `mensarium core open` or `mensarium client gateway open` opens it with a one-time login link, or log in with a token (`mensarium core token` / `mensarium client gateway token`, `--rotate` to replace it). Core rejects requests whose `Origin` doesn't match its `Host`; the gateway also rejects requests whose `Host` or `Origin` don't match its own address (`allowed_hosts` when it listens on other interfaces). There is one user and pairing equals full access, so any of them shows the full Core state — all chats, devices, approvals, settings; revoke a device in Devices to cut it off. If Core is down, a client's gateway shows a "Core is offline" banner and recovers on its own once Core is back.
- Memory (Settings → Memory): notes with `[[Title]]` links, an interactive relationship graph, and dreaming — nightly consolidation of new chats into long-term memory with a diary. The agent searches, reads, and adds to memory via `memory.*` tools; pinned and important notes are included in the system prompt.
- Skills (Settings → Skills, or `mensarium skills` on the Core host) are `SKILL.md` files in the [Agent Skills](https://agentskills.io) format: a frontmatter with `name` and `description` and markdown instructions for one kind of work. Bundled skills ship with the release; your own live in `~/.mensarium/core/skills/<name>/SKILL.md` and replace a bundled skill with the same name. The system prompt lists only names and descriptions in an `available_skills` block; the agent loads a skill with `skills.read` when the task matches (and reads files the skill ships with `path`). The optional `metadata.mensarium` block gates a skill: `os`, `requires.tools` (globs like `mcp.github.*`), `always`.
- Plugins (Settings → Plugins, or `mensarium plugins` / `mensarium mcp` on the Core host) extend the agent: device tools are command templates sent to a client as `shell.exec`; Core tools run in Core (`web.search` through Brave Search, `web.fetch` with internal addresses blocked); MCP servers run in Core or on a chosen device and give the agent `mcp.<server>.<tool>`. Plugins have a `category` the Plugins page groups them by, settings with secret fields that stay in Core, a risk level that decides approvals, and a catalog bundled with the release and refreshed from mensarium.com. A client runs an MCP server only if its program is in the device's allowlist and plugins from Core are allowed there. The catalog covers code hosting, docs and web search, browsers, databases, cloud and observability services, productivity and chat tools; servers that need your files, browser, docker or CLI logins run on a device. When a request needs something the agent has no tool for (web search, a browser, GitHub...), it looks up the catalog with `plugins.find` and proposes a plugin with `plugins.install`: the install always waits for your approval, even in full access, keys are entered only in Settings → Plugins, and a server that runs on a device is placed on the chat's device.
- Channels (Settings → Channels): talk to the agent from a messenger. Telegram: paste a bot token from @BotFather; the first Telegram account that writes to the bot becomes its owner and the only one it listens to. Messages become tasks on the device chosen in Settings → Channels, otherwise the first paired device, and continue the same chat; `/new` starts another, `/stop` stops the task. Approvals arrive as buttons, the answer as a message; the token stays in Core secrets.
- Automations (the Automations page above New chat, or `mensarium automations` on the Core host): a task the agent runs on its own on a schedule — once, every N minutes, or by cron — on a chosen device and access mode. Runs are logged with their result or error; repeated failures back off and eventually disable the automation, and a result can be sent to Telegram. The agent can propose and create an automation itself, but only after you say yes in the chat. Every paired device also gets a built-in automation that checks the client version every two hours and updates it to the Core version when the device allows remote updates; delete or disable it like any other.
- The web UI is available in English (default) and Russian, switchable in Settings → Overview.
- The worker verifies the signature, nonce, request TTL, policy hash, and presence of approval; paths are restricted to selected folders, programs to an allowlist; `.env` files, keys, and tokens are never read and are stripped from output.
- Core storage is SQLite in `~/.mensarium/core`; secrets are files with 0600 permissions and never reach the UI, prompts, or clients.
- After a Core restart, unfinished tasks move to `PAUSED` and do not resume on their own.

## Development

```sh
make dev     # .venv with the package in editable mode
make lint    # ruff + mypy
make dist    # dist/: install.sh, archive, and latest.json for distribution (requires clean git)
make release # dist + tag vX.Y.Z
make core    # Core in the foreground (needs ~/.mensarium/core/config.yaml, see mensarium core)
```
