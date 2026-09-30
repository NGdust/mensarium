# Tools reference

Every tool the agent can call: device tools that run on a client (or on Core's own built-in device), and Core tools that run inside Core itself. Risk levels and approval behavior are defined in code ([src/tool_runtime/registry.py](../src/tool_runtime/registry.py), [src/contracts/tools.py](../src/contracts/tools.py)) and enforced by the [policy engine](../src/policy_engine/engine.py) — see [Security model](security.md) for what each risk class and access mode means in general.

"Approval in Ask mode" below is what happens under the default `write`/`execute`/`network`/`destructive` approval policy ([src/profiles/coding-agent-v1.yaml](../src/profiles/coding-agent-v1.yaml)); a chat in Full access on a device that allows it skips these, except where noted.

## Device tools

Run on the device chosen for the chat (a paired client, or Core's own built-in device). Always-on tools are offered whenever the target reports them; desktop tools only appear when the device has the matching OS utility installed (macOS: `screencapture`, `osascript`; Linux: `grim`/`scrot`/`gnome-screenshot`/`import`/`spectacle`, `xdotool`/`ydotool`, `wmctrl`, `xdg-open`, `pactl`/`amixer`).

| Tool | What it does | Risk | Approval in Ask mode | Notes / limits |
|---|---|---|---|---|
| `files.list` | List files and directories | read | No | `depth` 1-5 (default 2) |
| `files.read` | Read a text file | read | No | `start_line`, `max_lines` 1-2000 (default 400); secret-looking paths are refused, see [Security](security.md#redaction) |
| `files.search` | Search file contents (ripgrep) | read | No | `max_results` 1-500 (default 100), optional `glob`, `regex` flag |
| `files.stat` | Type, size, permissions, mtime, line count | read | No | |
| `files.find` | Find files by name glob (e.g. `*.py`, `src/**/test_*.py`) | read | No | `max_results` 1-2000 (default 200); skips `.git`, `node_modules` and secret folders |
| `git.status` | `git status` of a repo inside an allowed root | read | No | |
| `git.diff` | `git diff` of a repo inside an allowed root | read | No | `staged` flag, optional `path` filter; not offered in `folder`-kind projects |
| `files.write` | Create or overwrite a whole text file (atomic) | write | Yes | content up to 2,000,000 characters; `create_dirs` default on |
| `files.edit` | Replace one exact text fragment in a file | write | Yes | `old`/`new` up to 200,000 characters each; must match exactly once unless `replace_all` |
| `files.mkdir` | Create a directory with parents | write | Yes | |
| `files.move` | Move or rename a file or directory | write | Yes | `overwrite` flag |
| `files.copy` | Copy a file or directory | write | Yes | `overwrite` flag |
| `files.delete` | Delete one file or an empty directory | destructive | Yes, with explicit destructive confirmation | not recursive |
| `system.info` | OS, arch, CPU, memory, load, disk space of allowed roots, uptime, agent version | read | No | |
| `process.list` | Running processes: pid, cpu, memory, user, command line | read | No | optional `filter` (max 200 chars), `limit` 1-500 (default 100) |
| `process.kill` | Stop a process of the device's own user by pid | destructive | Yes, with explicit destructive confirmation | `force` for SIGKILL instead of SIGTERM |
| `net.ports` | Listening TCP/UDP ports and their processes | read | No | |
| `net.http` | HTTP request from the device (reaches localhost services too) | network | Yes | `method` GET/HEAD/POST only; `headers` up to 20; `body` up to 200,000 chars; `timeout_s` 1-120 (default 30); `max_chars` 200-200,000 (default 20,000); can reference a secret as `{{secret:NAME}}`, see [Secrets](secrets.md) |
| `shell.exec` | Run one program in a directory, no shell | execute | Yes | no pipes/redirects/`&&`/`cd`/globs; program must be on the device's `command_allowlist` (ignored in Full access); `timeout_s` 1-3600 (default 120), capped by the device's `max_exec_seconds` (default 300); `secrets` names up to 20, passed as env vars |
| `shell.bash` | Run a bash script: pipes, redirects, loops, `&&`, any installed program | execute | Yes | script up to 50,000 chars, `stdin` up to 2,000,000; disabled entirely if the device sets `allow_shell: false`; `sudo`/other privileged commands are refused in Ask mode (denied outright, not just held for approval) |
| `screen.capture` | Screenshot of a display | execute | Yes | `display` 1-8 (default 1), `max_width` 640-3840 (default 1440); returned as an image, the last screenshot of the turn is attached to the chat reply |
| `screen.windows` | List open applications/windows, positions, sizes, focused one | read | No | |
| `input.mouse` | Move, click, double-click, right-click, scroll at screen coordinates | execute | Yes | coordinates come from a prior `screen.capture` |
| `input.type` | Type text into the focused window | execute | Yes | up to 5000 characters |
| `input.key` | Press a key or combination (`enter`, `escape`, `cmd+shift+t`, `ctrl+c`, ...) | execute | Yes | up to 60 characters |
| `app.open` | Open an application, file or URL | execute | Yes | up to 2000 characters |
| `system.volume` | Read, set, mute or unmute output volume | execute | Yes | `action` get/set/mute/unmute, `level` 0-100 for set |

## Core tools

Run inside Core, never on a device. Always available unless noted.

| Tool | What it does | Risk | Approval in Ask mode | Notes / limits |
|---|---|---|---|---|
| `skills.read` | Load a skill's full instructions (optionally one of its files) | read | No | offered only once a skill is installed, see [Skills](skills.md) |
| `memory.search` | Search long-term memory notes | read | No | `limit` 1-20 (default 8) |
| `memory.read` | Read one memory note in full, with its links | read | No | |
| `memory.save` | Add or append a durable memory note | read | No | title up to 120 chars, content up to 4000; `kind` fact/preference/project/person/device/howto, up to 8 `tags`; see [Memory](memory.md) |
| `plugins.find` | Search the plugin catalog for a capability | read | No | |
| `plugins.install` | Install/enable a catalog plugin, or enable an installed one | execute | **Always**, even in Full access | see [Plugins](plugins.md) |
| `plan.update` | Replace the plan shown above the chat input | read | No | up to 20 items |
| `agent.spawn` | Start a sub-agent on the same device, same tools and permissions | read | No | label up to 60 chars, task text up to 20,000; sub-agents cannot spawn further sub-agents and don't get plan tools |
| `agent.wait` | Wait for one or more sub-agents to finish and return their reports | read | No | up to 20 ids, empty = all |
| `automations.list` | List the user's automations | read | No | only in top-level chats that are not themselves an automation run (never sub-agents, never automation runs) |
| `automations.create` | Schedule this task to run again on its own | write | **Always**, even in Full access | same scope as above, after explicit user confirmation; see [Automations](automations.md) |
| `automations.delete` | Delete an automation by id | write | **Always**, even in Full access | same scope as above |
| `secrets.request` | Ask the user to save a secret through a form in the chat | read | No | same scope as above; the value never reaches the model, see [Secrets](secrets.md) |
| `device.update` | Update the client on this device to the Core version | read | No | offered only inside an automation run (it backs the built-in client-update automation), not in ordinary chats or sub-agents; no-op if already current, and the device itself can still refuse the update |

## Plugin-provided Core tools

These exist only once the corresponding plugin is installed and enabled ([src/plugins/builtin.py](../src/plugins/builtin.py), [src/plugins/google.py](../src/plugins/google.py)); see [Plugins](plugins.md) for installation, OAuth and per-plugin risk overrides.

| Tool | What it does | Risk (default) | Approval in Ask mode | Notes / limits |
|---|---|---|---|---|
| `web.search` | Search the web via Brave Search | network | Yes | needs a Brave API key configured; `count` 1-20 |
| `web.fetch` | Fetch a public page's readable text | network | Yes | `max_chars` 500-100,000 (default 20,000); refuses URLs that resolve to loopback/private/link-local addresses unless the plugin allows it; result is untrusted data, not instructions |
| `gmail.search` | List Gmail messages matching a query | read | No | `max_results` 1-25 (default 10) |
| `gmail.read` | Read one Gmail message | read | No | |
| `gmail.send` | Send or reply to a Gmail message | network | Yes | requires the separate `gmail.send` OAuth scope to have been granted |
| `drive.search` | Search Google Drive files | read | No | `max_results` 1-25 (default 10) |
| `drive.read` | Read a Google Drive file's content | read | No | Docs/Sheets/Slides are exported as text/CSV |

A plugin's own risk setting (Settings → Plugins) can raise or lower `web.search`/`web.fetch`'s default risk for that install.

## MCP server tools

Any MCP server placed in Core or on a device (by a plugin, or `mensarium mcp`) exposes its tools to the agent as `mcp.<server>.<tool>`. Their argument schema comes from the server itself, not from this registry; risk is the plugin's configured risk (`network` by default), automatically raised to `destructive` for a tool the server marks with `destructiveHint`. See [Plugins](plugins.md) for how servers are placed, disabled per tool, and what an MCP tool call looks like in the chat.
