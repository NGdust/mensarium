# Configuration

This page is the reference for Mensarium's data directory, its `config.yaml` files, the settings that live in the database instead, and the environment variables the code reads. For what a setting *does* in practice, the linked pages (especially [Core](core.md) and [Clients](clients.md)) go deeper; this page just lists what exists.

## Data directory (`~/.mensarium`)

Everything Mensarium stores lives under one directory, `~/.mensarium` by default; set `MENSARIUM_HOME` to use a different one (see [Environment variables](#environment-variables)). Roles that don't run on a machine simply have no folder for them — a client-only machine has no `core/`, a Core-only machine has no `client/`.

```
~/.mensarium/
├── core/                     Core's own data (only where Core runs)
│   ├── config.yaml           Core configuration — see below
│   ├── mensarium.db          SQLite database: tasks, chats, memory, settings, ...
│   ├── secrets/              Secret values, one file per secret, mode 0600
│   ├── keys/
│   │   └── core_ed25519.pem  Core's signing key
│   ├── artifacts/            Tool outputs and chat attachments
│   ├── skills/               User-added skills (SKILL.md folders)
│   ├── instructions/         AGENTS.md, SOUL.md, IDENTITY.md, USER.md
│   ├── logs/                 Created at startup, currently unused (the service log is core.log below)
│   ├── core.log, core.pid    Written by `mensarium service install core` / a backgrounded `core serve`
│   └── device/                The Core host's built-in device — same layout as client/ below
├── client/                    Client (worker/gateway) data (only on a paired client machine)
│   ├── config.yaml            Client configuration — see below
│   ├── keys/
│   │   └── client_ed25519.pem Client's signing key
│   ├── audit.jsonl            Local audit log of executed tool calls
│   ├── plugins.json           Cached state of plugins pushed from Core
│   ├── permissions.json       Cached OS permission state (macOS Screen Recording/Accessibility, etc.)
│   ├── secrets/
│   │   ├── gateway-token      Gateway's own login token
│   │   └── gateway-link       One-time login link state for the gateway
│   ├── backups/                Local scratch space used while restoring a .pab bundle
│   ├── client.log, client.pid  Worker service log/pid
│   └── gateway.log, gateway.pid Gateway service log/pid
├── projects/                   Project copies
│   ├── <project_id>/
│   │   ├── src/                 Clone of a project given by a git URL
│   │   ├── shadow.git            Hidden history for a "folder"-kind project
│   │   ├── repo.git              Bare repo used when this device is the project's executor
│   │   ├── mirror.git            Core-side mirror assembled from devices' bundles
│   │   └── wt/<task_id>/         One chat's working copy
│   ├── core-inbox/               Incoming bundle chunks, Core side
│   └── inbox/                    Incoming bundle chunks, client side
└── venv/, bin/, src/            Installed by install.sh
```

See [Skills](skills.md), [Memory](memory.md#instruction-files), [Projects](projects.md) and [Installation](installation.md) for the parts of this tree.

A pre-0.38 install's `target/` directory (and its `target_ed25519.pem` key) is renamed to `client/`/`client_ed25519.pem` automatically the first time the code touches it.

## `core/config.yaml`

Loaded once when `core serve` starts; see [What needs a restart](#what-needs-a-restart).

| Key | Type | Default | Meaning |
|---|---|---|---|
| `update_url` | string | `https://mensarium.com` | Release site the Core update in Settings → Overview checks and installs from; the `mensarium update` command does not read it |
| `log_level` | string | `INFO` | Python log level for the Core process |
| `server.host` | string | `0.0.0.0` | Bind address of the API/UI server |
| `server.port` | int | `8787` | Bind port |
| `server.public_url` | string | `http://127.0.0.1:8787` | URL clients, the gateway and the web UI use to reach this Core |
| `device.enabled` | bool | `true` | Whether Core runs a built-in worker on its own host — see [Core: the Core host as a device](core.md#the-core-host-as-a-device) |
| `device.name` | string \| null | `null` | Display name; defaults to the hostname |
| `device.roots` | list[string] | `[]` | Folders the built-in device may work in |
| `device.command_allowlist` | list[string] | see [Clients](clients.md#device-permissions) | Programs `shell.exec` may run on the built-in device |
| `device.allow_full_access` | bool | `true` | Whether the built-in device permits "Full access" chat mode |
| `device.allow_shell` | bool | `true` | Whether `shell.bash` is allowed on the built-in device |
| `device.allow_remote_plugins` | bool | `true` | Whether Core may start MCP servers on the built-in device |
| `plugins.catalog_url` | string \| null | `https://mensarium.com/dist/plugins.json` | Remote plugin catalog, merged with the bundled one — see [Plugins](plugins.md#the-catalog) |
| `llm.active_provider` | string | `ollama_cloud` | Id of the provider used for new chats and background work |
| `llm.providers.<id>.kind` | string \| null | — | Provider kind (`ollama_cloud`, `openai`, `claude_code`, ...) — see [LLM providers](providers.md) |
| `llm.providers.<id>.base_url` | string | — | HTTP base URL, or the CLI command for `claude_code`/`codex_cli` |
| `llm.providers.<id>.default_model` | string | — | Model used unless a chat picks another |
| `llm.providers.<id>.vision_model` | string \| null | `null` | Model substituted when a chat step includes an image |
| `llm.providers.<id>.api_key_ref` | string \| null | `null` | `secret://<name>` reference into `core/secrets/` |
| `llm.providers.<id>.timeout_s` | int | `90` | Request timeout |
| `llm.providers.<id>.max_retries` | int | `2` | Retries on transport errors / retryable HTTP status codes |
| `execution.approval_ttl_s` | int | `900` | How long an "Approve once" approval stays usable |
| `execution.request_ttl_s` | int | `120` | TTL on a signed execution request sent to a device (replay window) |
| `projects.sync_interval_s` | int | `600` | How often Core re-syncs each project's source in the background |

Provider entries are managed through Settings → Providers or the `mensarium core` wizard rather than hand-edited — see [LLM providers](providers.md#adding-a-provider). The full table above matches [src/core/config.py](../src/core/config.py).

## `client/config.yaml` (and `core/device/config.yaml`)

Both use the same schema (`ClientConfig`); the Core host's built-in device just keeps its copy under `core/device/` and has it kept in sync with the `device.*` keys of `core/config.yaml` (see [Core](core.md#the-core-host-as-a-device)). Loaded once when the worker/gateway process starts.

| Key | Type | Default | Meaning |
|---|---|---|---|
| `server` | string | — | Core's HTTP(S) URL |
| `ws_url` | string | — | Core's WebSocket URL (derived from `server`) |
| `target_id` | string | — | This device's id (`tgt_...`) |
| `workspace_id` | string | — | The single workspace's id |
| `name` | string | — | Display name |
| `core_public_key` | string | — | Core's Ed25519 public key, base64 |
| `core_fingerprint` | string | — | Fingerprint of that key, shown in the UI |
| `roots` | list[string] | — | Folders the agent may work in on this device |
| `command_allowlist` | list[string] | default developer-tools list — see [Clients](clients.md#device-permissions) | Programs `shell.exec` may run |
| `allow_full_access` | bool | `true` | Whether this device permits "Full access" chat mode |
| `allow_remote_update` | bool | `true` | Whether Core's UI may trigger `mensarium update` here |
| `allow_remote_plugins` | bool | `true` | Whether Core may start MCP servers on this device |
| `allow_shell` | bool | `true` | Whether `shell.bash` is allowed here |
| `limits.max_exec_seconds` | int | `300` | Upper bound on `shell.bash`/`shell.exec`/MCP call timeouts |
| `limits.max_stdout_bytes` | int | `1048576` (1 MiB) | Captured stdout/stderr size cap |
| `limits.max_artifact_bytes` | int | `26214400` (25 MiB) | Size cap for a single stored artifact |
| `worker.enabled` | bool | `true` | Run the agent's tools on this machine — see [Clients](clients.md#worker-and-gateway-roles) |
| `gateway.enabled` | bool | `false` | Serve the web UI on this machine |
| `gateway.host` | string | `127.0.0.1` | Gateway bind address |
| `gateway.port` | int | `8790` | Gateway bind port |
| `gateway.allowed_hosts` | list[string] | `[]` | Extra `host:port` values the browser may use to reach the gateway |
| `moved_to` | string \| null | `null` | Core address this client last followed to — see [`client move`](clients.md#client-move-if-core-moved) |

Full schema in [src/client/config.py](../src/client/config.py).

## Settings stored in the database, not in `config.yaml`

These are changed through the web UI or CLI, not by editing a file; they're kept as JSON values in the `kv` table of `core/mensarium.db` and take effect immediately (no restart).

| `kv` key | Holds | Changed via |
|---|---|---|
| `channels.telegram` | Bot token reference, chat/owner binding — see [Telegram](channels.md) | Settings → Channels |
| `push` | Web Push subscriptions and per-approval/finished-chat toggles — see [Browser notifications](notifications.md) | Settings → Notifications |
| `memory.center` | Id of the note pinned as the memory graph's center | Memory page |
| `memory.settings` | Dreaming toggle, hour, minimum importance, timezone — see [Memory](memory.md#dreaming) | Settings → Memory |
| `memory.last_scheduled`, `memory.dreamed_until` | Internal bookkeeping for the daily dreaming run | — (internal) |
| `skills.disabled` | Ids of skills turned off | Settings → Skills |
| `secrets.user` | User secret metadata: description, allowed devices (values themselves are files, not `kv`) — see [Secrets](secrets.md#where-values-live) | Settings → Secrets, `mensarium secrets` |
| `automations.update_seeded` | Internal one-time flag: has the built-in client-update automation been seeded | — (internal) |

## Environment variables

| Variable | Meaning |
|---|---|
| `MENSARIUM_HOME` | Overrides the data directory (default `~/.mensarium`) |
| `MENSARIUM_UPDATE_URL` | Overrides the site `mensarium update` and `mensarium version` fetch releases from on a Core host (default `https://mensarium.com`) |
| `MENSARIUM_SOURCE_DIR` | Overrides the source tree Core packages when a client fetches `install.sh`/the tarball from it, ahead of `$MENSARIUM_HOME/src` and the installed package's own location |
| `MENSARIUM_TELEGRAM_API` | Overrides the Telegram Bot API base URL (default `https://api.telegram.org`), for testing |
| `CLAUDE_CONFIG_DIR` | Where the `claude_code` provider looks for Claude Code's config/session files (default `~/.claude`) |
| `CODEX_HOME` | Where the `codex_cli` provider looks for Codex's config/session files (default `~/.codex`) |

`install.sh` itself additionally reads `MENSARIUM_HOME`, `MENSARIUM_SOURCE` and `MENSARIUM_BIN_DIR` before Mensarium is installed — see [Installation](installation.md).

## What needs a restart

`core/config.yaml` and `client/config.yaml` are each read once, at process startup. Editing either file by hand (rather than through the wizard or the web UI) requires restarting the process that owns it:

```sh
mensarium service restart core      # after editing core/config.yaml
mensarium service restart client    # after editing client/config.yaml
mensarium service restart gateway   # after editing the gateway.* keys
```

(or re-run the foreground command if you're not running it as a service). The `mensarium core`/`mensarium core setup` and `mensarium client`/`mensarium client setup` wizards write these files and restart the relevant service themselves when one is installed.

Changes made **through the web UI or CLI at runtime** apply immediately, without a restart:

- adding, editing, removing or switching the active LLM provider (Settings → Providers);
- everything in the [database-backed settings table](#settings-stored-in-the-database-not-in-configyaml) above;
- plugin install/uninstall/configuration, skills enable/disable, automations, secrets.

A device permission change (`roots`, `command_allowlist`, `allow_full_access`, etc.) is the one exception among client settings: Core hashes the device's policy into every execution request and the client rejects a mismatch, so a changed policy only takes effect once the worker restarts — the wizard/`client setup` does this automatically when a service is installed.

## See also

- [Core](core.md) — setting up and running Core
- [Clients](clients.md) — pairing, worker/gateway roles, device permissions
- [LLM providers](providers.md) — provider kinds and how to add one
- [Secrets](secrets.md) — where secret values live and how they're used
- [Backup and moving Core](backup-and-move.md) — what `core backup` includes from this layout
