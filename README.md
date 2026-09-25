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
| `mensarium target pair --server URL --code CODE --root DIR` | Pairing without the wizard (`--no-full-access`, `--no-remote-update` — restrictions on the device) |
| `mensarium target run` | Run Target Agent in the foreground |
| `mensarium service install\|restart\|logs core\|target` | Manage the service |
| `mensarium uninstall --purge` | Remove services and data |

## How it works

```
LLM proposal → schema validation → target capability check → policy evaluation
→ risk classification → approval (if required) → signed request → target execution
→ signed result → artifact → observation added to context → next step
```

- LLM providers: Ollama Cloud, local Ollama, llama.cpp — all through an OpenAI-compatible API; switching providers only changes config.
- Access modes per chat: "Ask before acting" (default) and "Full access". The machine running Core is always available to the agent as a device.
- Tools v0.1: `files.list`, `files.read`, `files.search`, `git.status`, `git.diff` (read, no confirmation needed) and `shell.exec` (always requires "Approve once" confirmation). File edits go through `git apply` with the patch on stdin.
- Memory (Settings → Memory): notes with `[[Title]]` links, an interactive relationship graph, and dreaming — nightly consolidation of new chats into long-term memory with a diary. The agent searches, reads, and adds to memory via `memory.*` tools; pinned and important notes are included in the system prompt.
- Plugins (Settings → Plugins): skills — instructions the agent loads via `skills.read` — and tools — command templates that are sent to the device as `shell.exec` and go through the same checks and approvals. The catalog ships with the release and updates from mensarium.com; a custom package is added via a YAML manifest.
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
