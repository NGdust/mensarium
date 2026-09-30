# Troubleshooting

Diagnostic commands and fixes for problems you can hit running Core or a client, grounded in the actual error messages in the code.

## Diagnostic commands

```sh
mensarium status              # what's installed/running on this machine: Core, its device, client worker/gateway
mensarium version             # installed version, and whether a newer one is published (--no-check to skip)
mensarium service logs core   # tail -F the service's log (role: core | client | gateway)
```

`mensarium status` prints "nothing configured; run `mensarium core` or `mensarium client`" when neither is set up on the machine. It also shows Core as "not responding" if `GET /healthz` on the configured port doesn't return 200 within 2 seconds.

### Log files

Service logs go to `~/.mensarium/<role-dir>/<role>.log` (`MENSARIUM_HOME` if set instead of `~/.mensarium`):

| Role | Log file |
|---|---|
| Core | `core/core.log` |
| Client worker | `client/client.log` |
| Client gateway | `client/gateway.log` |

On macOS, services run under `launchd` (both stdout and stderr point at the same log file above). On Linux with systemd available, services run as `systemd` user units (`mensarium-<role>.service`, or system-wide if installed as root) logging to the same file via `append:`. Without launchd or systemd, `mensarium service install` falls back to a detached background process, tracked by a pid file (`<role>.pid` next to the log) — `mensarium service stop <role>` reads that pid to kill it.

## Device offline / cannot pair

- **"pairing code is invalid, used or expired"** (`POST /v1/targets/pair`, HTTP 403) — pairing codes from `mensarium core pair-code` are one-time and valid 10 minutes. Generate a new one.
- **"pairing code already used"** — the code was already redeemed by another device; generate a new one.
- **"cannot reach core at `<server>`: `<error>`"** — the client couldn't reach the Core URL passed to `mensarium client pair --server ...` (wrong address, Core not running, or a firewall/network path issue). Check the URL matches what `mensarium status` or the web UI's Devices page shows for the Core, and that the Core process is actually running (`mensarium status` on the Core host).
- **"origin not allowed"** (HTTP 403 from Core's HTTP API) — Core rejects any browser request whose `Origin` header's host doesn't match the `Host` header it received. This shows up if you reach Core through a different hostname/port than the one the browser navigated to (for example, a reverse proxy that rewrites `Host` but not `Origin`, or accessing the API by IP while the page loaded by hostname). Make sure the address you configured as the Core's public URL is the one actually used to reach it. (This check does not apply to a gateway-tunneled request — a gateway only forwards `content-type`, `accept` and `last-event-id`.)

## Gateway says "Core is offline"

The gateway (`mensarium client gateway run`, `GET /v1/gateway` for status) returns this when it can't reach Core over its own client connection to relay a browser request — the underlying client-to-Core WebSocket is down. Check:

- The client's worker/gateway process is actually connected: `mensarium status` on that machine, or `mensarium client gateway status` for the gateway's own view (it reports `Core: connected` or `offline`).
- The Core host is reachable and running (`mensarium status` there).
- If the gateway's status also shows a `Rejected` reason, the pairing is no longer valid on the Core side (for example, the device was removed) — pair the client again.

## Login token lost or web UI login fails

- **"invalid token"** (HTTP 401 on `/v1/auth/login`) — the token pasted doesn't match the one Core (or a gateway) currently holds. Get the current one, or replace it:

```sh
mensarium core token             # print the Core web UI's login token
mensarium core token --rotate    # replace it; existing browser sessions are logged out
mensarium core open              # open the web UI with a fresh one-time login link instead of the token
```

Same for a client's gateway: `mensarium client gateway token [--rotate]` and `mensarium client gateway open`.

## LLM provider errors

- **Claude Code / Codex CLI providers**: "Cannot read Claude OAuth credentials...", "Claude usage polling requires subscription OAuth credentials...", "Claude usage authorization failed; renew login with `claude` on the Core host." — these mean the CLI tool on the Core host isn't logged in (or its login expired). Run `claude` (or `codex`) interactively on the Core host to (re-)authenticate.
- **"codex model/list returned no available models; check Codex login"** — same idea for Codex.
- **OpenAI-compatible providers** (Ollama, llama.cpp, LM Studio, OpenAI, OpenRouter, ...): errors surface as `transport error: <...>` (network/connection failure — check the base URL and that the server is running) or `HTTP <status>: <body>` (the endpoint responded but rejected the request — check the API key and model name in the provider's config).

## macOS permission prompts (Screen Recording / Accessibility)

Desktop tools (screenshots, clicks, keystrokes) need macOS to grant the client process Screen Recording and Accessibility. Mensarium asks once per installed version automatically; to force it again:

```sh
mensarium client permissions
```

If the worker service is running, this restarts it so macOS shows the prompts fresh; otherwise it triggers the OS prompts directly and you start the agent afterwards. Allow both in the dialogs, or grant them manually in **System Settings → Privacy & Security → Screen Recording / Accessibility** (look for "Mensarium Agent" or the Python interpreter, depending on how it was installed). Mouse moves additionally need `cliclick` (`brew install cliclick`); plain clicks work without it.

## Task stuck in `PAUSED` after a Core restart

This is expected: when Core starts, every task that was still active gets moved to `PAUSED` with reason `core restarted` (shown in the UI as "Core restarted, resume manually") — it does not resume by itself. Open the chat and press the play button ("Resume the agent"), which calls `POST /v1/tasks/{id}/resume`. A task also goes to `PAUSED` if the device it's running on goes offline mid-execution, or if you pause it yourself; the fix is the same in all three cases — resume once the device (and Core) are back.

## Port already in use

`mensarium core serve` (default port 8787) and `mensarium client gateway run` (default port 8790) will fail to start if something else is already bound to that port — including a previous Mensarium process that didn't exit cleanly (common with the plain-background-process service fallback used when neither `launchd` nor `systemd` is available). Before assuming a real conflict:

```sh
mensarium status                     # is a service for this role already marked running?
mensarium service stop core          # (or client/gateway) stops the tracked service/process cleanly
```

To run on a different port instead of freeing the old one: `mensarium core serve --port <port>` for Core, or edit `gateway.port` in the client's `config.yaml` (see [Configuration](configuration.md)) for the gateway.

## Update failures

`mensarium update` (`mensarium.cli.update`) can fail with:

- **"uv not found; re-run the installer: `curl -fsSL https://mensarium.com/install.sh | sh`"** — the `uv` binary Mensarium relies on for installs is missing.
- **"download failed: `<error>`"** — couldn't fetch the release archive from the update source.
- **"checksum mismatch: the downloaded archive differs from latest.json"** — the downloaded file's sha256 didn't match what `latest.json` advertised; try again, or check `--source` if you pointed it at a non-default server.
- **"archive has no pyproject.toml"** — the downloaded archive isn't a valid Mensarium release.
- **"install failed: `<uv pip install stderr>`"** — the actual package install step failed; the tail of `uv`'s error output is included.

`mensarium update --check` only checks without installing; `--force` reinstalls even if the version is already current; `--source <url>` points at a different update server than the default.
