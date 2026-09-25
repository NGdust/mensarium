English · [Русский](README.ru.md)

# Mensarium

A portable agent harness. **Core** (the main agent) calls the LLM, builds context, checks model-proposed actions against policies, waits for user approval, and writes an audit trail. **Target Agent** is a thin, LLM-free daemon on the managed machine: it holds an outgoing WebSocket connection to Core and executes only signed ED25519 requests.

The model never gets direct access to shell, files, network, or secrets: it only proposes a `tool_call`, and Core decides whether it can be executed.

## Installation

Core (once, on a server or laptop):

```sh
curl -fsSL https://mensarium.com/install.sh | sh -s -- --role core
```

Target (on every machine the agent will work on). The pairing code is created in the Core UI (Targets → Pair new target) or with `mensarium core pair-code`:

```sh
curl -fsSL https://mensarium.com/install.sh | sh -s -- --server http://<core-host>:8787 --code WOLF-SKY-4821
```

The Core UI shows a ready-made command for the target — it fetches the installer straight from your Core, so `--server` is not required.

The installer sets up [uv](https://docs.astral.sh/uv/) and Python 3.12 in `~/.mensarium`, puts the `mensarium` command in `~/.local/bin`, asks for settings, and registers a background service (launchd on macOS, systemd on Linux). Docker is not needed.

## Commands

| Command | What it does |
|---|---|
| `mensarium setup` | Interactive setup for Core or Target |
| `mensarium status` | What is installed and running |
| `mensarium version` | Version, roles on this machine, and available update |
| `mensarium update` | Update: Core from mensarium.com, a device from its own Core (`--check` only checks). From the web UI: Overview → "Update" for Core, Devices → "Update to …" for agents |
| `mensarium core serve` | Run Core in the foreground |
| `mensarium core token` | Token for logging into the web UI |
| `mensarium core pair-code` | One-time pairing code (10 minutes) |
| `mensarium core backup -o file.pab` / `restore file.pab` | Encrypted transfer of Core to another host |
| `mensarium target pair --server URL --code CODE --root DIR` | Pairing without the wizard (`--no-full-access`, `--no-remote-update`, `--no-shell` — restrictions on the device) |
| `mensarium target run` | Run Target Agent in the foreground |
| `mensarium target permissions` | Ask the OS again for screen recording and accessibility |
| `mensarium plugins list [--catalog]`, `info ID`, `install ID\|file.yaml`, `update ID`, `remove ID` | Manage plugins of the Core on this machine |
| `mensarium plugins config ID KEY=VALUE [--secret KEY] [--placement core\|DEVICE] [--risk RISK]` | Plugin settings; secrets are asked without echo |
| `mensarium mcp add NAME --command 'npx -y pkg' \| --url URL [--secret-env KEY] [--device NAME]` | Add an MCP server in the Core or on a device; `mcp list`, `probe`, `tools`, `remove` |
| `mensarium skills list`, `show NAME`, `install DIR\|SKILL.md`, `enable\|disable NAME`, `remove NAME` | Skills of the Core on this machine |
| `mensarium target plugins` | MCP servers the Core runs on this device |
| `mensarium service install\|restart\|logs core\|target` | Manage the service |
| `mensarium uninstall --purge` | Remove services and data |

## How it works

```
LLM proposal → schema validation → target capability check → policy evaluation
→ risk classification → approval (if required) → signed request → target execution
→ signed result → artifact → observation added to context → next step
```

- LLM providers: Ollama Cloud, local Ollama, llama.cpp, LM Studio, OpenAI, OpenRouter or any OpenAI-compatible server — all through the OpenAI-compatible API. They are added, checked and switched in Settings → Providers (or in `mensarium setup`); the active provider changes without a restart and keys stay in Core secrets.
- Access modes per chat: "Ask before acting" (default) and "Full access". The machine running Core is always available to the agent as a device.
- Device tools, all native in the Target Agent: read without confirmation (`files.list`, `files.read`, `files.search`, `files.stat`, `files.find`, `git.status`, `git.diff`, `system.info`, `process.list`, `net.ports`), changes with confirmation (`files.write`, `files.edit`, `files.mkdir`, `files.move`, `files.copy`, `net.http`), irreversible ones always confirmed (`files.delete`, `process.kill`), and `shell.bash` for real bash scripts (reviewed and approved per script, `sudo` refused, can be disabled per device with `--no-shell`). `shell.exec` runs one allowlisted program without a shell. Desktop tools appear when the device has the OS utilities: `screen.capture` (a screenshot the model sees as an image; set a "model for images" on the provider, e.g. `gemma4` on Ollama Cloud, and Core switches to it on steps with a screenshot), `screen.windows`, `input.mouse`, `input.type`, `input.key`, `app.open`, `system.volume`. On macOS the agent runs through `~/Applications/Mensarium.app`, so Privacy & Security shows Mensarium (not Python); it asks for Screen Recording and Accessibility after install and after every update (`mensarium target permissions` asks again); mouse moves need `brew install cliclick`.
- Memory (Settings → Memory): notes with `[[Title]]` links, an interactive relationship graph, and dreaming — nightly consolidation of new chats into long-term memory with a diary. The agent searches, reads, and adds to memory via `memory.*` tools; pinned and important notes are included in the system prompt.
- Skills (Settings → Skills, or `mensarium skills` on the Core host) are `SKILL.md` files in the [Agent Skills](https://agentskills.io) format: a frontmatter with `name` and `description` and markdown instructions for one kind of work. Bundled skills ship with the release; your own live in `~/.mensarium/core/skills/<name>/SKILL.md` and replace a bundled skill with the same name. The system prompt lists only names and descriptions in an `available_skills` block; the agent loads a skill with `skills.read` when the task matches (and reads files the skill ships with `path`). The optional `metadata.mensarium` block gates a skill: `os`, `requires.tools` (globs like `mcp.github.*`), `always`.
- Plugins (Settings → Plugins, or `mensarium plugins` / `mensarium mcp` on the Core host) extend the agent: device tools are command templates sent to a device as `shell.exec`; Core tools run in the Core (`web.search` through Brave Search, `web.fetch` with internal addresses blocked); MCP servers run in the Core or on a chosen device and give the agent `mcp.<server>.<tool>`. Plugins have a `category` the Plugins page groups them by, settings with secret fields that stay in the Core, a risk level that decides approvals, and a catalog bundled with the release and refreshed from mensarium.com. A device runs an MCP server only if its program is in the device's allowlist and plugins from the Core are allowed there. The catalog covers code hosting, docs and web search, browsers, databases, cloud and observability services, productivity and chat tools; servers that need your files, browser, docker or CLI logins run on a device.
- The web UI is available in English (default) and Russian, switchable in Settings → Overview.
- Target verifies the signature, nonce, request TTL, policy hash, and presence of approval; paths are restricted to selected folders, programs to an allowlist; `.env` files, keys, and tokens are never read and are stripped from output.
- Core storage is SQLite in `~/.mensarium/core`; secrets are files with 0600 permissions and never reach the UI, prompts, or the target.
- After a Core restart, unfinished tasks move to `PAUSED` and do not resume on their own.

## Development

```sh
make dev     # .venv with the package in editable mode
make lint    # ruff + mypy
make dist    # dist/: install.sh, archive, and latest.json for distribution (requires clean git)
make release # dist + tag vX.Y.Z
make core    # Core in the foreground (needs ~/.mensarium/core/config.yaml, see mensarium setup)
```
