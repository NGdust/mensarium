# Mensarium

**Your own agent cloud. One Core, every machine you own.**

Mensarium is a self-hosted agent harness. You install **Core** on a server or a laptop, pair your other computers, and give the agent work from a browser or Telegram. The model never touches a machine directly: it only proposes an action, Core checks it against a policy, asks you when the action changes something, and sends the machine a signed request. Everything, from chats to keys and the activity log, stays on your hardware.

<img src="landing/shots/architecture.png" alt="Core on atlas in the middle: tasks come from the browser and approvals from Telegram, signed requests go to the machines atlas, studio, forge and pi, and the model is Claude Code, Codex, Ollama or an OpenAI-compatible API" width="100%">

- **One place for the agent.** Core talks to the model, keeps memory, plugins, skills, automations and a hash-chained activity log, and serves the web UI.
- **All your machines.** Mac and Linux machines join with a one-time code. They dial out to Core, open no ports, and run only requests Core signed.
- **You stay in control.** Reading is free; changing files, running programs and network access wait for your approval in the browser or in Telegram. Full access is a per-chat switch on devices that allow it.
- **Any model.** Claude Code or Codex already on the Core host, Ollama, llama.cpp, LM Studio, OpenAI, OpenRouter or any OpenAI-compatible endpoint.
- **One install line.** No Docker, no accounts, nothing hosted.

<table>
  <tr>
    <td width="50%"><img src="landing/shots/project.jpg" alt="Project homelab: three chats, each on its own branch"><br><sub>Projects: every chat works in its own copy on its own branch.</sub></td>
    <td width="50%"><img src="landing/shots/automations.jpg" alt="Automations with schedules and run results"><br><sub>Automations: scheduled runs that finish with a result.</sub></td>
  </tr>
  <tr>
    <td width="50%"><img src="landing/shots/devices.jpg" alt="Devices: atlas runs Core, studio has a gateway, forge and pi are paired"><br><sub>Devices: the Core host is a device too.</sub></td>
    <td width="50%"><img src="landing/shots/audit.jpg" alt="Activity log with a hash for every event"><br><sub>Activity log: every event is chained to the previous one's hash.</sub></td>
  </tr>
</table>

## Install

```sh
curl -fsSL https://mensarium.com/install.sh | sh
```

Works on macOS and Linux. The installer puts [uv](https://docs.astral.sh/uv/), Python 3.12 and the package into `~/.mensarium` and the `mensarium` command into `~/.local/bin`. It asks nothing; all setup happens in the command itself.

## Quick start

### 1. Set up Core

On the machine that should be the brain, a home server or the laptop you use most:

```sh
mensarium core
```

The wizard has four steps:

1. **Network**: the API port (8787 by default), who can reach Core (your network or only this machine) and the address other machines will use.
2. **LLM provider**: Claude Code and Codex on this machine are found automatically and need no key; otherwise pick Ollama, llama.cpp, LM Studio, OpenAI, OpenRouter or any OpenAI-compatible server and the default model.
3. **This machine as a device**: its name, the folders the agent may work in, which programs it may run, and whether full access, bash scripts and plugin servers are allowed here.
4. **Service**: run Core in the background so it starts on login or boot.

At the end it prints a one-time link to the web UI.

### 2. Open the web UI and give the first task

Open the printed link. Later, run `mensarium core open` for a new link or log in with the token from `mensarium core token`.

<img src="landing/shots/hero-new.jpg" alt="A new chat: device atlas, Ask before acting, the model picked" width="100%">

Pick the device and the access mode under the input, describe the task and send it. In **Ask before acting** the agent reads on its own and stops for your approval before it changes files, runs a program or goes to the network. **Full access** skips those stops on a device that allows it.

### 3. Add your other machines

On the Core machine, create a pairing code (it works once and expires in ten minutes):

```sh
mensarium core pair-code
```

The same code is in the web UI under **Devices → Pair a device**, together with both commands. On the other machine:

```sh
curl -fsSL https://mensarium.com/install.sh | sh
mensarium client
```

The client wizard asks for the Core address, the folders and programs the agent may use there, the pairing code, and two roles: run the agent's tools here (`worker`) and open the web UI here (`gateway`). The device shows up online within a few seconds. Running `mensarium client` on the Core machine itself is refused, because that machine is already a device.

### 4. Approve from your phone (optional)

In **Settings → Channels**, paste a bot token from [@BotFather](https://t.me/BotFather) and send the bot any message. The first account that writes becomes its owner, and the bot ignores everyone else. Messages become tasks, answers come back as messages, and approvals arrive as **Run once** and **Reject** buttons.

### 5. Keep it updated

```sh
mensarium update
```

On the Core machine this updates Core from mensarium.com. Every paired device gets a built-in automation that updates its client to the Core version, if the device allows remote updates; `mensarium update` on a client does the same by hand.

## How it works

Core is the only place that talks to the model. Clients only ever talk to Core, never to each other:

```
                     ┌──────────────────────────────┐
   Telegram ────────►│ core                         │
   (Core channel)    │  orchestrator, LLM, policy   │
   browser  ────────►│  UI, own device, approvals   │
                     │  sqlite, secrets             │
                     │  cron, WSS /v1/clients, CLI  │
                     └──────┬────────────┬──────────┘
                    WSS     │            │     WSS
              ┌─────────────┘            └──────────────┐
              ▼                                         ▼
 ┌──────────────────────────┐                  ┌──────────────┐
 │ client (laptop)          │                  │ client       │
 │  worker: runs tools      │                  │ (server 2)   │
 │  gateway: 127.0.0.1:8790 │                  │  worker      │
 │   └─ UI + tunnel to core │                  └──────────────┘
 └────────────▲─────────────┘
              │ http://127.0.0.1:8790
         ┌────┴────┐
         │ browser │
         └─────────┘
```

Every action the model proposes goes through the same path before anything runs:

```
LLM proposal → schema validation → target capability check → policy evaluation
→ risk classification → approval (if required) → signed request → target execution
→ signed result → artifact → observation added to context → next step
```

The machine checks the signature, the nonce, the deadline and the policy hash, and runs the action only inside the folders and programs you allowed. `.env` files, keys and tokens are cut out of what the agent reads.

## Documentation

Full documentation lives in [docs/](docs/README.md):

- **Getting started**: [installation](docs/installation.md), [Core](docs/core.md), [clients](docs/clients.md), [LLM providers](docs/providers.md), [chats](docs/chats.md)
- **Features**: [projects](docs/projects.md), [automations](docs/automations.md), [plugins](docs/plugins.md), [skills](docs/skills.md), [secrets](docs/secrets.md), [memory and instructions](docs/memory.md), [Telegram](docs/channels.md), [browser notifications](docs/notifications.md)
- **Operations**: [CLI reference](docs/cli.md), [configuration](docs/configuration.md), [backup and moving Core](docs/backup-and-move.md), [troubleshooting](docs/troubleshooting.md)
- **Internals**: [security model](docs/security.md), [tools reference](docs/tools.md), [architecture](docs/architecture.md), [development](docs/development.md)

## Development

```sh
make dev     # .venv with Python 3.12 and the package linked from src/
make test    # ruff + mypy + unit tests, the same check CI runs
```

See [docs/development.md](docs/development.md) for running Core and clients locally, the release process and the site, [CONTRIBUTING.md](CONTRIBUTING.md) for pull requests, and [SECURITY.md](SECURITY.md) for reporting vulnerabilities.
