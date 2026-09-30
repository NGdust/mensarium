# Clients

A client is another machine paired with Core: it dials out to Core over WebSocket, opens no incoming ports, and runs only tool calls Core signed. This page covers pairing, the worker and gateway roles, device permissions, macOS setup, and what happens when Core is unreachable. Running Core itself already makes its own host a device — see [Core: the Core host as a device](core.md#the-core-host-as-a-device); `mensarium client` refuses to run on that machine.

<img src="../landing/shots/devices.jpg" alt="Devices: the Core host and three paired clients" width="100%">

## Installing on another machine

```sh
curl -fsSL https://mensarium.com/install.sh | sh
mensarium client
```

See [Installation](installation.md) for what the install script does.

## Setup wizard

```sh
mensarium client
```

If this machine is already paired, it shows the current state and offers to keep it, follow a moved Core (see [`client move`](#client-move-if-core-moved)), or pair again with a new code. Otherwise it walks through four steps:

1. **Connect to the Core** — the Core's URL; the wizard waits until it answers `/healthz`.
2. **Workspace access** — folders the agent may work in, which programs `shell.exec` may run, whether full access and MCP plugins are allowed, and whether the agent may run bash scripts here. See [Device permissions](#device-permissions) below. Also asks whether to allow the Core to update this agent remotely.
3. **Pairing** — a name for this machine and the pairing code from `mensarium core pair-code` (format `WORD-WORD-1234`).
4. **Service** — worker and/or gateway roles (below), and whether to run them as background services.

## Non-interactive pairing

```sh
mensarium client pair \
  --server http://192.168.1.10:8787 \
  --code WORD-WORD-1234 \
  --root /home/me/projects \
  [--root DIR ...] \
  [--name my-laptop] \
  [--full-access/--no-full-access] \
  [--remote-update/--no-remote-update] \
  [--remote-plugins/--no-remote-plugins] \
  [--shell/--no-shell]
```

All boolean flags default to allowed. `--root` is repeatable and at least one is required. If run from a TTY, it continues into the interactive role/service setup afterwards; non-interactively it just pairs and, if a client service is already installed, restarts it.

## Worker and gateway roles

A paired client can run either or both:

- **worker** (`worker.enabled`, default on) — runs the agent's tools on this machine. `mensarium client run` runs it in the foreground; as a service it's the `client` unit.
- **gateway** (`gateway.enabled`, default off, turned on in the wizard) — serves the web UI on this machine and relays its requests to Core over the same signed WebSocket connection (its own session, separate from the worker's). `mensarium client gateway run` runs it in the foreground; as a service it's the `gateway` unit.

Gateway settings:

| Key | Default | Meaning |
|---|---|---|
| `gateway.enabled` | `false` | Serve the web UI on this machine |
| `gateway.host` | `127.0.0.1` | `127.0.0.1` for this machine only, `0.0.0.0` for other machines on the network too |
| `gateway.port` | `8790` | Local port for the web UI |
| `gateway.allowed_hosts` | `[]` | `host:port` values the browser is allowed to use, required in addition to `127.0.0.1:<port>`/`localhost:<port>` when `host` is `0.0.0.0` |

```sh
mensarium client gateway open              # open the browser with a one-time login link
mensarium client gateway token [--rotate]  # print (or replace) the standing login token
mensarium client gateway status            # gateway running? connected to Core?
```

Gateway login works the same way as Core's own (session cookie, `SameSite=Strict`, 30 days); it additionally rejects any request whose `Host` header isn't one of `allowed_hosts` (plus its own loopback addresses), and any `Origin` that doesn't match `Host`. The gateway token and its cookie never leave this machine — Core only ever sees the already-authenticated HTTP request the gateway relays, never the gateway's own credentials.

## Device permissions

Asked at pairing (wizard step 2, or the `client pair` flags) and re-askable with `mensarium client setup`:

| Setting | CLI flag | Meaning |
|---|---|---|
| Workspace roots | `--root DIR` (repeatable) | Folders the agent may read and, in Ask mode, write in on this device |
| Program allowlist | (wizard only: default/any/custom list) | Programs `shell.exec` may run; `["*"]` allows any program on `PATH` |
| Full access | `--full-access`/`--no-full-access` | Whether this device permits the "Full access" chat mode at all (no per-action approvals, no root/allowlist restrictions, system commands like `sudo`/`systemctl` permitted) |
| Remote update | `--remote-update`/`--no-remote-update` | Whether Core's web UI may trigger `mensarium update` on this machine |
| Remote plugins | `--remote-plugins`/`--no-remote-plugins` | Whether Core may start MCP servers on this device (still limited to programs in the allowlist) |
| Bash scripts | `--shell`/`--no-shell` | Whether the agent may use `shell.bash` here (each script still needs your approval; `sudo` is refused even then) |

The default program allowlist (used unless you pick "any" or a custom list) is: `git, python, python3, pytest, uv, pip, pip3, poetry, ruff, mypy, black, node, npm, pnpm, yarn, go, cargo, make, ls, cat, head, tail, wc, grep, rg, find, diff, patch, tree, echo, mkdir, touch, cp, mv, jq`.

Every execution request from Core carries a hash of the device's current policy (roots, allowlist, full-access flag) and tool list; if it doesn't match what the client itself computed at startup, the request is rejected — so a permission change only takes effect after the worker restarts (the wizard/`client setup` restarts it automatically when a service is installed).

For the full list of device tools and their risk levels, see [Tools reference](tools.md).

## macOS: app bundle and permissions

On macOS, a paired worker runs through `~/Applications/Mensarium Agent.app` — a tiny launcher around the actual agent process, so macOS attributes permission prompts and the Privacy & Security entry to "Mensarium Agent" instead of the Python interpreter. It's (re)installed automatically whenever the `client` service is (re)installed, unless something else already occupies that path.

Desktop tools (`screen.capture`, `screen.windows`, `input.mouse`, `input.type`, `input.key`, `app.open`, `system.volume`) need macOS **Screen Recording** and **Accessibility** permissions, requested the first time each installed version starts and again after every update. To ask again (e.g. after denying them, or to check current state):

```sh
mensarium client permissions
```

This restarts the worker if it's running as a service (macOS then shows its permission dialogs again), or asks directly and shows the current status otherwise. Mouse control additionally needs `cliclick` (`brew install cliclick`); the wizard offers to install it via Homebrew if missing.

On Linux, the same command reports which of `xdotool`, `wmctrl`, `grim`/`scrot` are present and prompts to install the missing ones (`apt install xdotool wmctrl scrot`, or `grim` on Wayland) — there's no OS permission dialog to trigger, availability is just whether the tools exist.

## Revoking a device

In the web UI, Devices → revoke, or `POST /v1/targets/{id}/revoke` — sets the target `revoked`, disconnects it immediately, and its client rejects reconnecting (closes with a fatal WebSocket code and stops retrying for 5 minutes at a time) until paired again with a new code. The Core host's own built-in device cannot be revoked this way; disable it instead in Core's config (`device.enabled: false`).

## When Core is offline

A worker or gateway that can't reach Core keeps retrying with exponential backoff (starting at 1s, doubling up to a 30s cap). The gateway's web UI shows a "Core is offline" banner and recovers automatically once Core answers again. Chats and approvals queued on Core simply wait; nothing the client can't reach is lost.

## `client move` (if Core moved)

If Core's address changed (see [Backup and moving Core](backup-and-move.md#moving-core-to-another-machine)), a client usually switches automatically: Core signs a `core.moved` message to every connected client before it stops, each client remembers the new address and switches to it the next time the old one doesn't answer. To do it by hand, or to check/set the remembered address:

```sh
mensarium client move [URL]
```

Without `URL` it uses the address Core last announced, if any. It re-proves the new Core holds the same signing key this client was paired with (`GET /v1/core/identity`, signed) before switching — so this only works against the *same* Core at its new address, not a fresh one; a genuinely new Core needs a fresh pairing code.

## See also

- [Core](core.md) — setting up Core, pairing codes, the web UI
- [Security model](security.md) — approvals, signed requests, redaction
- [Tools reference](tools.md) — every device tool and its risk level
