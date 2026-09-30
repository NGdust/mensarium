# Mensarium documentation

Mensarium is a self-hosted agent harness: one **Core** talks to the model, and your machines (**clients**) run the actions it proposes after Core has checked them and, when needed, you have approved them. Start with [Installation](installation.md) and [Setting up Core](core.md); the rest can be read in any order.

## Getting started

| Page | What it covers |
|---|---|
| [Installation](installation.md) | Requirements, the install script, updating and uninstalling |
| [Core](core.md) | Setting up and running Core, the web UI, the Core host as a device |
| [Clients](clients.md) | Pairing other machines, the worker and gateway roles, macOS permissions |
| [LLM providers](providers.md) | Claude Code, Codex, Ollama, llama.cpp, LM Studio, OpenAI, OpenRouter and other OpenAI-compatible APIs |
| [Chats](chats.md) | Using the web UI: devices, access modes, approvals, attachments, plans and sub-agents |

## Features

| Page | What it covers |
|---|---|
| [Projects](projects.md) | Folders and git repositories where every chat works in its own copy and branch |
| [Automations](automations.md) | Tasks the agent runs on a schedule |
| [Plugins](plugins.md) | Device tools, Core tools and MCP servers, OAuth sign-in |
| [Skills](skills.md) | `SKILL.md` instructions the agent loads for particular kinds of work |
| [Secrets](secrets.md) | API keys and tokens the agent uses by name without seeing them |
| [Memory and instructions](memory.md) | Long-term notes, dreaming, and the `AGENTS.md` / `SOUL.md` / `IDENTITY.md` / `USER.md` files |
| [Telegram](channels.md) | Talking to the agent and approving actions from Telegram |
| [Browser notifications](notifications.md) | Web Push for approvals and finished chats |

## Operations

| Page | What it covers |
|---|---|
| [CLI reference](cli.md) | Every `mensarium` command and option |
| [Configuration](configuration.md) | The `~/.mensarium` layout, config files, environment variables |
| [Backup and moving Core](backup-and-move.md) | Encrypted `.pab` backups, restoring, moving Core to another machine |
| [Troubleshooting](troubleshooting.md) | Status, logs and common problems |

## Internals

| Page | What it covers |
|---|---|
| [Security model](security.md) | What the model can and cannot do, approvals, signed requests, redaction |
| [Tools reference](tools.md) | Every tool the agent can call, with its risk level |
| [Architecture](architecture.md) | Components, protocol, task lifecycle, source layout |
| [Development](development.md) | Working on Mensarium itself: dev setup, tests, releases |
