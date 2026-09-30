# Secrets

User secrets are API keys, tokens and passwords the agent can use in shell commands and HTTP requests by name, without ever seeing the value itself. This page covers naming and value rules, per-device scope, the three ways to add a secret, how the agent uses one, and where values live.

## What a secret is

A secret has a **name** (used by the agent), a **value** (never shown to the agent, the UI after saving, or logs), a **description**, and a list of **devices** it may be used on. Names and metadata are stored in the Core database; each value is a separate file in the Core's secrets folder.

Naming rules ([src/contracts/secrets.py](../src/contracts/secrets.py)):

- Pattern `^[A-Z][A-Z0-9_]{1,63}$` — upper snake case, 2-64 characters.
- Reserved names are rejected: `PATH`, `HOME`, `USER`, `SHELL`, `PWD`, `LANG`, `TMPDIR`, `LD_PRELOAD`, `BASH_ENV`, `ENV`, `IFS`, `NODE_OPTIONS`, `PYTHONPATH`.
- Reserved prefixes are rejected: `LC_`, `MENSARIUM_`, `DYLD_`, `LD_`.

Value rules: at least 4 characters, at most 16 KB (`MAX_SECRET_BYTES`).

## Scope

Each secret carries a `targets` list: `["*"]` (every device, the default) or specific device ids. A tool call that needs a secret is denied if the device it would run on is not in the secret's target list — the policy check happens on the Core (`SecretStore.resolve`) before any request is signed.

## Adding a secret

**Settings → Secrets** — "Add secret" opens a form for name, value, description and target devices; existing secrets can be edited (the value field shows "Saved. Type to replace") or deleted. The chat input also warns when what you are about to send looks like a key ("This looks like a key. Save it as a secret instead of sending it to the chat?") and offers to save it and reference it as `{{secret:NAME}}` instead.

CLI ([src/cli/secrets.py](../src/cli/secrets.py)):

```sh
mensarium secrets list
mensarium secrets set NAME [--description TEXT] [--target DEVICE_ID ...]
mensarium secrets rm NAME
```

`secrets set` reads the value interactively without echoing it. Without `--target`, a new secret is available on every device (`*`); repeat `--target` for specific devices.

The agent's own path: it calls the `secrets.request` tool (risk `read`, added only to top-level chats — never to sub-agent tasks or automation runs) instead of asking for a key in a message. This shows a "The agent asks for a secret" card in the chat with a form; you fill in the value there, and the agent is told only whether it was saved or declined, never the value:

```
"The user saved secret NAME. Use it by name; you will not see its value."
"The user declined to save secret NAME."
```

The request expires after `execution.approval_ttl_s` (900s by default, [src/core/config.py](../src/core/config.py)) with no answer.

## How the agent uses a secret

The system prompt lists the names and descriptions of secrets available on the active device under `## Secrets` ([src/agent_core/context.py](../src/agent_core/context.py)); the agent never sees values there.

- **`shell.bash` / `shell.exec`**: list the names in the `secrets` argument, then refer to the value as `$NAME` in the script/args. The client puts the value into the shell process's environment and masks it (and the name) out of stdout, stderr and error text.
- **`net.http`**: write `{{secret:NAME}}` inside `url`, a header value, or `body`. The Core fills the placeholder in only the copy of the arguments sent to the device; the stored arguments, events, audit log and prompt keep the placeholder text, never the value ([src/shared/secret_refs.py](../src/shared/secret_refs.py)).

A tool call that references a secret is only decided once: `Decision.secrets` collects the names from the proposed arguments, the orchestrator resolves them against `SecretStore` and the device's declared `secrets` capability, and **always** routes the call through approval — even when the chat is in Full access mode (`set_mode(full)` does not auto-approve a call that uses a secret). After approval, values are re-read fresh (not cached from evaluation time), the `secrets` key is stripped out of the stored tool arguments, and the resolved values travel only inside `ExecutionRequest.secrets` of that one signed request.

## Masking

Wherever a secret value could appear in output — shell stdout/stderr on the client, HTTP responses relayed through `net.http`, and the Core's own event/audit trail — it is replaced with `[secret:NAME]` before being stored or displayed (`mask_secrets` in [src/shared/secret_refs.py](../src/shared/secret_refs.py); the client applies the same redaction before truncating output, and any other exception from a shell run is reported only by its type, never its message, so a value cannot leak through an error).

## Where values live

Secret values are files named `user-<NAME>` in the Core's `secrets` folder (`MENSARIUM_HOME/core/secrets`, see [docs/configuration.md](configuration.md)); metadata (description, targets, timestamps) lives in the Core database under the `secrets.user` key. Both are included in `.pab` backups (see [docs/backup-and-move.md](backup-and-move.md)).

## Transport note

`ExecutionRequest.secrets` travels to the device inside the same signed WebSocket message as the rest of the tool call. Over `ws://` (plain, unencrypted) that value is not protected by the transport itself — only the request signature guarantees it was not tampered with, not that it stayed private in transit. For a device reached over a network you do not fully trust, put the Core behind HTTPS so the client connects over `wss://` (the client's WebSocket URL is derived from the Core's configured `server.public_url`, see [docs/configuration.md](configuration.md)); on `localhost` this does not matter.

## See also

- [Plugins](plugins.md) — plugin settings marked `secret: true` are stored the same way, under a different key prefix, and never reach the model or a device directly.
- [Security model](security.md) — the wider approval and signing model this fits into.
- [Chats](chats.md) — the secret-request card and approval flow in the chat UI.
