# Backup and moving Core

Core can export its data as an encrypted, portable bundle (`.pab`) and restore it — on the same machine or a different one. Moving to a new machine reuses the same mechanism, plus a step that tells paired clients where Core went so they follow on their own. This page covers `core backup`, `core restore`, the move flow, and the manual fallback (`client move`).

## `core backup`

```sh
mensarium core backup [-o|--output FILE.pab]
```

Interactive: it asks

1. whether this is a move to another server (see [Moving Core to another machine](#moving-core-to-another-machine)),
2. which optional items to include besides the core data that's always in,
3. a passphrase (entered twice) to encrypt the bundle.

Default output name: `mensarium-backup-YYYY-MM-DD.pab` in the current directory.

### What goes in

Always included ("core"): the SQLite database, `config.yaml`, `secrets/`, `keys/`, the built-in device's own directory (`device/`), `skills/`, `instructions/`.

Optional, chosen at export time:

| Item | Included by default | Contents |
|---|---|---|
| `artifacts` | yes | Attachments and tool results stored by Core |
| `logs` | no | Core's log files |
| `projects` | yes, if any exist | Project copies and chat history on this machine (see [Projects](projects.md)) |
| `root:N` (one per outermost folder) | yes | The Core host's own device folders (`device.roots` in `core/config.yaml`) — only offered when the Core-host device is enabled |

Folders under `node_modules`, `.venv`, `venv`, `__pycache__`, `.mypy_cache`, `.ruff_cache`, `.pytest_cache`, `.tox`, `.next`, `.nuxt`, `.gradle`, `dist`, `build`, `target` are skipped inside `projects` and device root folders (rebuildable, so not worth the space); the wizard reports how much was skipped.

### Format and encryption

`.pab` v2: a stream of AES-256-GCM-sealed chunks (1 MiB each) wrapping a `tar.gz`. The encryption key is derived from your passphrase with `scrypt` (a random 16-byte salt per bundle, `N=2^15, r=8, p=1`); each chunk's nonce is derived from a random 7-byte prefix plus its own counter, so chunks can't be reordered or replayed. There's no way to recover a bundle without the passphrase — Core doesn't keep it. Older `.pab` v1 bundles (single AES-GCM blob, no chunking) are still readable by `core restore`.

The output prints a SHA-256 of the finished file for you to verify against, if you copy it somewhere separately.

## `core restore`

```sh
mensarium core restore BUNDLE.pab
```

Asks for the passphrase, then:

- if the bundle carries device root folders, asks where to put each one (defaulting to the same path under the new `$HOME` if it moved, or lets you pick a new location if the default path isn't writable);
- stops the Core service first if one is installed;
- extracts everything; an existing `~/.mensarium/core` (and `~/.mensarium/projects`, if the bundle has projects) is moved aside as `<name>.before-restore-<timestamp>` rather than overwritten;
- if the bundle wasn't from a move, asks for the public URL clients should use to reach this Core (defaults to what's already in the config; if you change it, existing clients need `mensarium client move <url>`);
- rewrites `device.roots` and each project's `source_path` to the new locations, and re-links (`git worktree repair`) every project's git worktrees;
- restarts the Core service if it was running before, and checks the model provider answers (relevant mainly when Claude Code/Codex needs a fresh login on the new machine).

Restoring is destructive to what's already there only in the "moved aside" sense above — nothing is deleted outright.

## Moving Core to another machine

`core backup` with the "move" option does the whole handoff in one flow:

1. **On the old machine:**
   ```sh
   mensarium core backup
   ```
   Answer yes to "Is this a move to another server?" and give the new Core's URL (where clients will reach it once it's up). Core then:
   - signs and sends a `core.moved` message to every currently connected client, telling it the new address (clients act on it only once their old connection actually stops answering, so nothing switches early);
   - stops its own service (or, running in the foreground, waits for you to Ctrl+C it) so nothing changes on disk after the snapshot;
   - writes the `.pab` bundle with `moved_to` recorded in its manifest.

   Clients that were offline at that moment don't get told; the output lists them by name so you can run `mensarium client move <url>` on each once the new Core is up.

2. **Copy the bundle to the new machine, install Mensarium there, and restore:**
   ```sh
   curl -fsSL https://mensarium.com/install.sh | sh
   mensarium core restore mensarium-backup-....pab
   ```
   Because the manifest has `moved_to`, restore skips the "what URL should clients use" question and applies it directly.

3. **Clients that were online during step 1** switch by themselves: each remembers the new address and connects to it as soon as its connection to the old address drops (which it already did, since the old Core stopped). Clients that were offline (or that missed the message) need the manual fallback below, once, from that same machine.

The new Core must hold the **same signing key** as the old one — which restoring the bundle gives it automatically, since `keys/` is part of the core data that's always included — so clients can verify it's genuinely a continuation of the Core they were paired with, not a different one.

## `client move` (manual fallback)

```sh
mensarium client move [URL]
```

Run on a client that didn't pick up the move automatically. Without `URL`, it uses whatever address the client last remembered being told (if any). It proves the Core at that URL holds the same key this client was paired with (`GET /v1/core/identity`, a signed nonce challenge) before switching — see [Clients: `client move`](clients.md#client-move-if-core-moved) for the mechanics and why a genuinely different Core can't be adopted this way.

## See also

- [Clients](clients.md) — worker/gateway roles, what happens while Core is unreachable
- [Configuration](configuration.md) — the `~/.mensarium` layout backups draw from
- [Security model](security.md) — how signed requests and keys are handled
