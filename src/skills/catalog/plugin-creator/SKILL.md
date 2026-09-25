---
name: plugin-creator
description: Write a Mensarium plugin manifest in YAML, command tools or MCP server, for the user to install.
---
# Plugin creator

Goal: write a valid plugin YAML manifest, then hand it back as text since the agent cannot install it
into the Core itself.

1. Read src/contracts/plugins.py with files.read for the exact schema: `id` matches
   `^[a-z0-9][a-z0-9-]{1,48}$`; `name`/`summary`/`description` are plain text or `{en, ru}` maps;
   `category` is one of development, browser, web, databases, cloud, observability, productivity,
   communication, automation, system, other; a plugin needs at least one of `tools`, `builtin`, `mcp`.
2. Read two catalog examples with files.read to match style: a command-tool plugin (e.g.
   src/plugins/catalog/docker.yaml or git-history.yaml) and an MCP plugin (e.g. mcp-github.yaml or
   mcp-context7.yaml).
3. For a command-tool plugin: each entry in `tools` has a dotted `name` (e.g. `foo.bar`), a
   `description`, a `risk` (read/write/execute/network/destructive), and `argv` where `argv[0]` is a
   bare program name with no path or placeholder; every `{placeholder}` used in `argv` or `cwd` needs a
   matching entry in `parameters`, and a boolean parameter used in `argv` needs a `flag`.
4. For an MCP plugin: `mcp.transport` is `stdio` (a bare `command`, no path or placeholder) or `http`
   (a `url` starting with `http(s)://` or a placeholder); `placement` is `core` (Core runs or connects
   it) or `device` (it needs device-local files, e.g. a kubeconfig or a repo path); secrets go only
   through `config` fields marked `secret: true`, filled into `env` or `headers` as `{key}`
   placeholders, never hardcoded.
5. Declare every config field the tools or the `mcp` block reference under `config`, marking
   `secret: true` for anything sensitive and `required: true` for anything without a safe default.
6. Set `risk` per tool (or on the `mcp` block) honestly: `read` for inspection only, `write` /
   `execute` / `network` / `destructive` for anything that changes state, reaches the network, or could
   be destructive; this drives whether the user is asked for approval.
7. Check the manifest against plugins.py's own checks before returning it: unique tool names, every
   placeholder declared in `parameters` or `config`, `argv[0]`/`command` free of paths and
   placeholders, at least one of `tools`/`builtin`/`mcp` present.
8. Do not attempt to install the plugin yourself; you have no access to the Core's plugin store.

Report format:
- The complete plugin manifest in one fenced ```yaml``` code block.
- One line telling the user to install it via "Your own plugin" on the Plugins page, or
  `mensarium plugins install file.yaml`.
