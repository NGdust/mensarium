# CLI Reference

The `mensarium` command manages Core, clients and their shared background services on this machine, and talks to a running Core's API for plugins, skills, secrets, automations and projects. Run `mensarium --help` or `mensarium <command> --help` for the same information from the tool itself.

## Where to run what

| Command group | Run on |
|---|---|
| `core` | The Core host (the server) |
| `client`, `client gateway` | A client machine (any other machine you pair) |
| `service` | Whichever machine runs the role you name (`core`, `client` or `gateway`) |
| `plugins`, `mcp`, `skills`, `secrets`, `automations`, `projects` | Core host or any paired client (talks to the Core's API either way) |
| `version`, `update`, `status`, `uninstall` | Any machine with Mensarium installed |

`mensarium project` is a hidden alias of `projects`. `mensarium target` is a hidden, deprecated alias of `client`, kept for old scripts.

## version

Show the installed version, and whether a newer one is published.

```sh
mensarium version [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--check` / `--no-check` | `--check` | Also check `dist/latest.json` on the update server for a newer release |

## update

Update Mensarium: on the Core host it downloads from mensarium.com (or `MENSARIUM_UPDATE_URL`); on a client it downloads from its own Core, so a client always matches its Core's version. Restarts whichever services (`core`, `client`, `gateway`) are installed on this machine.

```sh
mensarium update [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--check` | off | Only report whether an update is available, install nothing |
| `--force` | off | Reinstall even if the reported version matches the current one |
| `--source` | Core: `https://mensarium.com`; client: its Core's URL | Override the update server |

## status

Print what is installed and running on this machine: data home, service backend, and (if configured) Core health/URL/provider/device, or client name/Core address/worker state/gateway state. Prints "nothing configured" if neither Core nor client is set up here.

```sh
mensarium status
```

## uninstall

Stop and remove the background services (`core`, `client`, `gateway`) installed on this machine.

```sh
mensarium uninstall [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--purge` / `--no-purge` | `--no-purge` | Also ask to delete the whole Mensarium home directory (data, keys, everything) and the `~/.local/bin/mensarium` symlink |

## core

Run on the Core host. With no subcommand, `mensarium core` opens the interactive setup wizard if the Core isn't configured yet, or prints its status if it is (same as `core setup` / a status view; not a scriptable command — use the subcommands below for automation).

### core setup

Configure or reconfigure the Core interactively: network/port, LLM provider, this machine as the Core's own built-in device, and whether to install it as a background service. If already configured, first asks to keep-and-restart or reconfigure.

```sh
mensarium core setup [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--service` / `--no-service` | ask interactively | Install (or skip) the background service, without the prompt |

### core serve

Run the Core server in the foreground (used by the background service; also useful for debugging with logs on the terminal).

```sh
mensarium core serve [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--host` | value from `config.yaml` | Override the bind host for this run |
| `--port` | value from `config.yaml` | Override the port for this run |

### core pair-code

Create a one-time pairing code (valid 10 minutes, single use) for pairing a client with `mensarium client pair` or the `client` setup wizard.

```sh
mensarium core pair-code
```

Example:

```sh
mensarium core pair-code
# on the other machine:
mensarium client pair --server http://192.168.1.10:8787 --code word-word-1234 --root ~/Projects
```

### core token

Print the token used to log into the Core's own web UI (separate from a one-time login link).

```sh
mensarium core token [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--rotate` | off | Replace the token; any open browser sessions are logged out |

### core open

Print a one-time login link for the Core's web UI and open it in the default browser.

```sh
mensarium core open
```

### core backup

Interactively build and write an encrypted `.pab` bundle of the Core (database, config, secrets, keys, built-in device, instructions, skills are always included; artifacts, logs, projects, and the built-in device's folders are offered as choices with their sizes). Also asks whether this is a move to another server: if yes, it notifies paired clients of the new URL and stops the Core's service on this machine once the bundle is written.

```sh
mensarium core backup [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `-o`, `--output` | `mensarium-backup-<date>.pab` in the current directory | Output file path |

See [Backup and move](backup-and-move.md) for the bundle format and the move workflow.

### core restore

Restore the Core from a `.pab` bundle: stops the Core's service while restoring, asks for the passphrase, and (for a bundle with device folders) confirms or remaps where those folders land on this machine.

```sh
mensarium core restore BUNDLE
```

| Argument | Meaning |
|---|---|
| `bundle` | Path to the `.pab` file (required) |

## client

Run on a client machine — any machine other than the Core host that you want the agent to work on. Refuses to set up if this machine already runs the Core (the Core is its own first device; use `mensarium core open` there). With no subcommand, opens the interactive setup wizard if not yet paired, or prints status if it is.

### client setup

Configure or reconfigure this client interactively: connect to a Core, choose accessible folders and shell permissions, pair, and choose which of worker/gateway to run as background services. If already paired, first offers to keep-and-restart, follow the Core to a new address, or pair again.

```sh
mensarium client setup [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--server` | ask interactively | Core URL |
| `--code` | ask interactively | Pairing code from the Core |
| `--name` | ask interactively (hostname) | Name for this client |
| `--service` / `--no-service` | ask interactively | Install (or skip) the background services |

### client pair

Pair this machine with a Core without the pairing prompts — the scriptable equivalent of the setup wizard's pairing step. After pairing: if run from a terminal, continues into the interactive worker/gateway role wizard; otherwise restarts the `client` service if one is installed, or prints a hint to run `client setup` / `service install client`.

```sh
mensarium client pair [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--server` | *(required)* | Core URL, e.g. `http://192.168.1.10:8787` |
| `--code` | *(required)* | Pairing code from the Core |
| `--root` | *(required, repeatable)* | Allowed workspace root folder; pass `--root` once per folder |
| `--name` | hostname | Client name |
| `--full-access` / `--no-full-access` | `--full-access` | Allow full-access chats (all files/programs within OS permissions, no per-action approval) |
| `--remote-update` / `--no-remote-update` | `--remote-update` | Allow the Core's web UI to update this agent |
| `--remote-plugins` / `--no-remote-plugins` | `--remote-plugins` | Allow the Core to run MCP servers on this device |
| `--shell` / `--no-shell` | `--shell` | Allow the agent to run bash scripts here (each run still needs approval) |

Example:

```sh
mensarium client pair --server http://192.168.1.10:8787 --code word-word-1234 \
  --root ~/Projects --root ~/Work --name laptop
```

### client move

The Core moved to a new address (after `core backup` as a move, or a manual DNS/IP change): switch this client to the new URL. The Core must be the same one (same signing key); without an argument, prompts for the URL (defaulting to any address the Core already announced).

```sh
mensarium client move [URL]
```

| Argument | Meaning |
|---|---|
| `url` | The Core's new URL (optional; asked interactively if omitted) |

### client plugins

List the MCP servers the Core has placed on this device, as of the last sync (read-only, local cache — no Core round-trip).

```sh
mensarium client plugins
```

### client permissions

Ask the OS again for the desktop-automation permissions the agent needs (screen recording, accessibility on macOS; checks for `xdotool`/`wmctrl`/`grim`/`scrot` on Linux). On macOS this restarts the client service if it is running (which triggers the OS permission dialogs) or asks for the permissions directly if not; either way it warns when `cliclick`, needed for mouse moves, is missing.

```sh
mensarium client permissions
```

### client run

Run the client worker (agent tool execution) in the foreground. Fails if the worker is disabled in this client's config.

```sh
mensarium client run
```

## client gateway

The client's local web UI process: serves the UI on this machine and tunnels browser requests to the Core over the same paired connection. Runs alongside (or instead of) the worker, controlled independently.

### client gateway run

Run the gateway in the foreground. Fails if the gateway is disabled in this client's config.

```sh
mensarium client gateway run
```

### client gateway token

Print the token used to log into this gateway's web UI.

```sh
mensarium client gateway token [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--rotate` | off | Replace the token; open browser sessions are logged out |

### client gateway open

Print a one-time login link for this gateway's web UI and open it in the default browser.

```sh
mensarium client gateway open
```

### client gateway status

Show whether the gateway process is running and whether it is connected to the Core (and why not, if the Core rejected it — usually needs re-pairing).

```sh
mensarium client gateway status
```

## service

Manage the background service for a role on this machine: `launchd` on macOS, `systemd` where available on Linux, otherwise a plain background process (started with `nohup`-style detachment, which does **not** restart on reboot). Every subcommand takes the same `role` argument.

| Argument | Meaning |
|---|---|
| `role` | One of `core`, `client`, `gateway` |

### service install

Install and start the background service for `role`.

```sh
mensarium service install ROLE
```

### service uninstall

Stop and remove the background service for `role`.

```sh
mensarium service uninstall ROLE
```

### service stop

Stop the service; it starts again on next login/boot (or with `service restart`) unless also uninstalled.

```sh
mensarium service stop ROLE
```

### service restart

Restart the service.

```sh
mensarium service restart ROLE
```

### service logs

Follow the service's log file (`tail -F`).

```sh
mensarium service logs ROLE [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--lines` | `100` | Lines to show before following |

## plugins

Manage the Core's plugins (device tools, Core tools, and MCP servers) through its API — runs from the Core host or from any paired client, reaching the Core's API directly (loopback) or through the client's signed tunnel.

### plugins list

List installed plugins, or the whole catalog.

```sh
mensarium plugins list [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--catalog` | off | Show every catalog plugin, not just installed ones |
| `--json` | off | Print machine-readable JSON instead of a table |

### plugins info

Show a plugin's description, settings and current status.

```sh
mensarium plugins info PLUGIN_ID
```

### plugins install

Install a plugin, either by catalog id or from a local plugin manifest file (`.yaml`/`.yml`/`.json`).

```sh
mensarium plugins install SOURCE
```

| Argument | Meaning |
|---|---|
| `source` | Catalog id, or a path to a plugin manifest file |

### plugins update

Update an installed plugin to the version currently in the catalog.

```sh
mensarium plugins update PLUGIN_ID
```

### plugins remove

Remove a plugin and its stored secrets.

```sh
mensarium plugins remove PLUGIN_ID [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `-y`, `--yes` | off | Skip the confirmation prompt |

### plugins enable / plugins disable

Turn a plugin on or off without removing it (settings are kept while disabled).

```sh
mensarium plugins enable PLUGIN_ID
mensarium plugins disable PLUGIN_ID
```

### plugins config

Change a plugin's settings, or print them if called with no values. `KEY=VALUE` arguments set plain settings; secret settings are entered without echo.

```sh
mensarium plugins config PLUGIN_ID [KEY=VALUE ...] [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--secret` | — | Name of a secret setting to enter (prompted, repeatable) |
| `--clear-secret` | — | Name of a secret setting to delete (repeatable) |
| `--placement` | — | Where an MCP server runs: `core` or a device name |
| `--risk` | — | Risk level of the plugin's tools: `read`, `execute`, `write`, `network`, `destructive` |

### plugins probe

Restart the plugin's MCP server now and list the tools it reports.

```sh
mensarium plugins probe PLUGIN_ID
```

## mcp

Manage MCP servers — a thin view over the subset of `plugins` that are MCP servers, each one added or removed as an `mcp-<name>` plugin.

### mcp list

List installed MCP servers with where they run and their status.

```sh
mensarium mcp list
```

### mcp add

Add a custom MCP server that runs in the Core or on a named device.

```sh
mensarium mcp add NAME [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--command` | — | Command line of a stdio server, e.g. `'npx -y pkg'` (mutually exclusive with `--url`) |
| `--url` | — | URL of a streamable HTTP server (mutually exclusive with `--command`) |
| `--env` | — | Environment variable `KEY=VALUE` (repeatable) |
| `--secret-env` | — | Secret environment variable name, entered without echo (repeatable) |
| `--header` | — | HTTP header `KEY=VALUE` (repeatable) |
| `--secret-header` | — | Secret HTTP header name, entered without echo (repeatable) |
| `--device` | Core | Run this server on a named device instead of the Core |
| `--risk` | `network` | Risk of its tools: `read`, `execute`, `write`, `network`, `destructive` |
| `--description` | empty | What the server is for |

Example:

```sh
mensarium mcp add fs --command 'npx -y @modelcontextprotocol/server-filesystem /data' --risk write
```

### mcp remove

Remove an MCP server.

```sh
mensarium mcp remove NAME [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `-y`, `--yes` | off | Skip the confirmation prompt |

### mcp probe

Connect to the server now and list its tools.

```sh
mensarium mcp probe NAME
```

### mcp tools

Show an MCP server's tools, or hide/show specific tools from the agent.

```sh
mensarium mcp tools NAME [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--disable` | — | Hide a tool from the agent (repeatable) |
| `--enable` | — | Show a previously hidden tool again (repeatable) |

## skills

Manage the Core's skills (`SKILL.md` instructions the agent loads for particular kinds of work) through its API.

### skills list

List bundled skills and your own, with their enabled/always/OS/required-tools state.

```sh
mensarium skills list
```

### skills show

Print a skill's full `SKILL.md` text.

```sh
mensarium skills show NAME
```

### skills install

Add a skill from a local `SKILL.md` file or a folder containing one; it becomes one of your own skills (shadowing a bundled skill of the same name if there is one).

```sh
mensarium skills install SOURCE
```

| Argument | Meaning |
|---|---|
| `source` | Path to a `SKILL.md` file, or a folder that contains one |

### skills enable / skills disable

Offer the skill to the agent, or hide it (the file is kept either way).

```sh
mensarium skills enable NAME
mensarium skills disable NAME
```

### skills remove

Delete one of your own skills; a bundled skill of the same name (if any) is used again afterward.

```sh
mensarium skills remove NAME [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `-y`, `--yes` | off | Skip the confirmation prompt |

## secrets

Manage user secrets (API keys and tokens the agent uses by name without seeing the value) through the Core's API. See [Secrets](secrets.md) for how the agent requests and uses them.

### secrets list

List secrets by name, description, allowed devices and last update time — never values.

```sh
mensarium secrets list
```

### secrets set

Add or replace a secret. The value is prompted for without echo, not passed as an argument.

```sh
mensarium secrets set NAME [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `-d`, `--description` | kept from existing secret, else empty | Human-readable description |
| `--target` | kept from existing secret, else all devices (`*`) | Device id allowed to use this secret (repeatable) |

### secrets rm

Delete a secret.

```sh
mensarium secrets rm NAME
```

## automations

Manage automations (tasks the agent runs on a schedule) through the Core's API. See [Automations](automations.md) for schedule syntax and run semantics.

### automations list

List automations with their schedule, device, next run and last run status.

```sh
mensarium automations list
```

### automations show

Show one automation's settings and its 10 most recent runs.

```sh
mensarium automations show AUTOMATION_ID
```

### automations run

Trigger an automation immediately, outside its schedule.

```sh
mensarium automations run AUTOMATION_ID
```

### automations enable / automations disable

Turn an automation on or off.

```sh
mensarium automations enable AUTOMATION_ID
mensarium automations disable AUTOMATION_ID
```

### automations remove

Delete an automation and its run history.

```sh
mensarium automations remove AUTOMATION_ID [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `-y`, `--yes` | off | Skip the confirmation prompt |

## projects

Manage projects (folders and git repositories the agent works on in isolated per-chat copies) through the Core's API. See [Projects](projects.md) for how snapshots, branches and syncing work. `mensarium project` is a hidden alias for this whole group.

### projects list

List projects with kind, source device, path, status and chat count.

```sh
mensarium projects list
```

### projects create

Create a project either from a git repository (cloned on the Core host) or from a folder on a named device.

```sh
mensarium projects create [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--device` | — | Device name or id that has the folder (used with `--path`) |
| `--path` | — | Absolute path (or `~`-path) to the folder on that device |
| `--git` | — | Git repository URL to clone on the Core host |
| `--name` | folder/repo name | Project name |

Give either `--git`, or both `--device` and `--path`.

### projects init

Run **on the target machine itself** (the Core host, or a paired client): registers a folder on this machine as a project directly, without going through `projects create` on another host. The folder must already be inside this device's allowed roots; on a client, if it isn't, the command offers (interactively, needs a TTY) to add it and restarts the client. Waits up to 10 minutes for the initial read to finish.

```sh
mensarium projects init [PATH] [OPTIONS]
```

| Argument/Option | Default | Meaning |
|---|---|---|
| `path` | current directory | Folder to register |
| `--name` | folder name | Project name |

### projects sync

Re-read the project's source folder now, instead of waiting for the next scheduled sync.

```sh
mensarium projects sync PROJECT_ID
```

### projects delete

Delete a project and its chats. Files in the source folder are never touched.

```sh
mensarium projects delete PROJECT_ID [OPTIONS]
```

| Option | Default | Meaning |
|---|---|---|
| `--remove-shadow` | off | Also delete the hidden version history (`shadow.git`) of a folder-kind project |
| `-y`, `--yes` | off | Skip the confirmation prompt |
