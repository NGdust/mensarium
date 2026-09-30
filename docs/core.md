# Core

Core is the agent's brain: it talks to the model, keeps the database, serves the web UI, and is itself the first device the agent can work on. This page covers setting it up, running it, the web UI, pairing, and the Core host as a device.

## Choosing a Core machine

Core should run on a machine you keep on: a home server, NAS or a laptop you use most. It needs no incoming ports opened for clients beyond the one port it listens on, and the machine it runs on becomes the agent's first device by default.

## Setup wizard

```sh
mensarium core
```

If Core is already configured, this shows its current state instead. `mensarium core setup` always starts the wizard; if Core is already configured it first asks whether to keep the configuration and (re)start, or reconfigure. The wizard has four steps:

1. **Network** — the API port (default `8787`), who may reach Core (your local network, bound to `0.0.0.0`, or only this machine, `127.0.0.1`), and the public URL clients and the web UI will use to reach it (defaults to your LAN IP or `127.0.0.1` depending on the previous answer).
2. **LLM provider** — Claude Code and Codex installed on this machine are detected automatically (no API key needed, used through your existing subscription); otherwise choose Ollama Cloud, local Ollama, llama.cpp, LM Studio, OpenAI, OpenRouter or another OpenAI-compatible server, enter its base URL and API key, and pick a default model from the ones it reports.
3. **This machine as a device** — its name, the folders the agent may work in, which programs `shell.exec` may run (a default developer-tools list, any program on `PATH`, or a custom list), and whether full access, plugin MCP servers and bash scripts are allowed here. See [Clients](clients.md#device-permissions) for what each of these means.
4. **Service** — whether to run Core as a background service that starts on login/boot.

At the end it prints a one-time login link to the web UI. See [LLM providers](providers.md) for provider details.

## Running Core

Foreground, for development or debugging:

```sh
mensarium core serve [--host HOST] [--port PORT]
```

As a background service (installed by the wizard, or explicitly):

```sh
mensarium service install core
mensarium service stop core
mensarium service restart core
mensarium service logs core [--lines N]
mensarium service uninstall core
```

The service backend is chosen automatically:

| Platform | Backend | Unit name | Logs |
|---|---|---|---|
| macOS | `launchd` | `com.mensarium.core` (`~/Library/LaunchAgents/com.mensarium.core.plist`) | `~/.mensarium/core/core.log` |
| Linux with systemd | `systemd` --user (or system-wide if run as root) | `mensarium-core.service` | `~/.mensarium/core/core.log` |
| Linux without systemd | detached background process | none (no restart on reboot) | `~/.mensarium/core/core.log` |

`mensarium status` shows whether Core is running, its URL, active provider/model, and its own device.

## The web UI

Core serves the web UI itself, on `<public_url>` (e.g. `http://192.168.1.10:8787`).

```sh
mensarium core open     # open the browser with a fresh one-time login link
mensarium core token    # print the standing login token
mensarium core token --rotate   # replace it; open browser sessions are logged out
```

Login sets an HTTP-only, `SameSite=Strict` session cookie good for 30 days. There is one user: pairing (and knowing the token) is full access to everything Core holds — all chats, devices, approvals and settings.

Core's own request middleware rejects any request whose `Origin` header doesn't match its `Host` header, so a page on another site cannot call the API even with the cookie present. On top of the cookie, Core also accepts a bearer token (`Authorization: Bearer <token>`) from `127.0.0.1`/`::1` only — a separate token generated for CLI use (`mensarium plugins`, `mensarium skills`, etc. talk to a locally running Core this way).

If you expose Core beyond your LAN, put it behind a reverse proxy with HTTPS — Core itself serves plain HTTP and has no TLS support built in. The session cookie and the `Authorization` header are otherwise sent as configured regardless of transport, so an unencrypted connection exposes them in transit.

## The Core host as a device

By default (`device.enabled: true` in `core/config.yaml`) Core runs a worker inside its own process, attached to itself over loopback through the exact same signed-frame protocol as a remote client — there is no separate code path. This is why the machine running Core needs no separate `mensarium client` install to also be a device: it's the first device automatically, configured in the wizard's step 3 or later with `mensarium core setup`.

Its identity (signing key, login token, audit log) lives under `~/.mensarium/core/device/`, independent of Core's own key. Its settings are the `device:` section of `core/config.yaml` — `enabled`, `name`, `roots`, `command_allowlist`, `allow_full_access`, `allow_shell`, `allow_remote_plugins` — same meaning as the equivalent client settings in [Clients](clients.md#device-permissions). It cannot be remotely updated or revoked from the UI (it updates and stops together with Core).

If you previously ran `mensarium client` on the same machine and later set up Core there too, Core adopts that client on startup: same device id, key, folders and token move into Core, the client's and gateway's services are removed, and its old data directory is renamed to `client.adopted`. Its chats, projects and automations carry over. `mensarium client` refuses to run at all on a machine that already runs Core (`This machine runs the Core and is already its device`).

## Pairing other machines

Pairing codes let another machine join as a client without sharing your login token:

```sh
mensarium core pair-code
```

Prints a one-time code in the form `WORD-WORD-1234`, valid for **10 minutes**, usable once. The same can be generated from the web UI (Devices → Pair a device), which calls `POST /v1/targets/pairing-codes`. Pairing itself (`POST /v1/targets/pair`) is rate-limited: after 10 failed attempts in 10 minutes it returns `429` regardless of the code.

On the other machine:

```sh
curl -fsSL https://mensarium.com/install.sh | sh
mensarium client pair --server http://<core-address> --code WORD-WORD-1234 --root <dir>
# or interactively:
mensarium client
```

See [Clients](clients.md) for the client-side wizard, flags and device permissions.

## See also

- [Clients](clients.md) — pairing, worker/gateway roles, device permissions
- [Backup and moving Core](backup-and-move.md) — `.pab` backups and moving Core to another machine
- [Configuration](configuration.md) — the full `core/config.yaml` layout
- [Security model](security.md) — approvals, signed requests, risk levels
