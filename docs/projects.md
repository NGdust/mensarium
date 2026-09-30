# Projects

A project lets a chat work on a folder or git repository instead of an unscoped device root. Each chat gets its own isolated copy on a `mensarium/<slug>-<id>` branch, so parallel chats and your own working copy never collide, and every turn is committed automatically.

<img src="../landing/shots/project.jpg" alt="A project with three chats, each on its own branch" width="100%">

## Two kinds of project

A project is one of two kinds, decided when it is created:

- **`repo`** — a git repository. Version history lives in the repository itself (or in Core's own clone, for a project created from a URL); your checkout is never touched.
- **`folder`** — any other folder. Mensarium keeps its own hidden version history for it in a bare repository (`shadow.git`) next to the folder; there is no visible `.git` and the agent is told not to run git commands itself.

The kind is detected from the source: a folder that already has `.git` becomes `repo`, otherwise `folder`. A project created from a `git_url` is always `repo`.

## Creating a project

### From a folder on a device (UI)

In the web UI, **Projects → New project**, pick an online device that supports projects and browse to a folder. Only devices whose client reports `projects` and `projects_root` in its capabilities are offered.

### From a folder, from the CLI

Register the current directory on the machine you run the command on:

```sh
mensarium project init [PATH] [--name NAME]
```

This resolves the local machine to its device id (the paired client, or Core's own device if run on the Core host), checks the folder is inside that device's allowed roots (offering to add it if not, when run interactively), creates the project, and waits until Core has read it. `mensarium projects init` is the same command under the `projects` group.

Equivalent, from any machine that can reach Core's API:

```sh
mensarium projects create --device NAME --path DIR
```

`--path` must be absolute or start with `~`. `--device` accepts a device name or id (`mensarium projects list` / the web UI's device list shows both).

### From a git URL

```sh
mensarium projects create --git URL
```

Core clones the repository onto its own machine, under `~/.mensarium/projects/<project_id>/src`, and every chat works from that clone — so the project keeps working even with your laptop closed. Accepted URL forms: `https://…`, `ssh://…`, `git://…`, or `user@host:path`. Access to a private repository uses whatever git is already configured for the Core process's user on its machine (an SSH key for `ssh://`, a credential helper for `https://`). **Sync** (`mensarium projects sync PROJECT_ID`, or the button in the UI) runs `git pull --ff-only` on the clone and re-reads the snapshot.

### Project settings

`mensarium projects` also has `list`, `sync`, and `delete [--remove-shadow] [--yes]`. `delete` removes the project and its chats from Core; files in the source folder are never touched. `--remove-shadow` additionally deletes the hidden version history of a `folder` project (requires the source device online). A project's name, whether to include remote-tracking branches, whether to `git fetch` before each snapshot, the default base branch, size/file limits, project instructions, and the default executor device are all editable through `PUT /v1/projects/{id}` (exposed in the web UI's project settings, not yet in the CLI).

## Chats with a workspace vs. chats without one

By default a new chat in a project gets its own **workspace**: a `git worktree` (for `repo` projects) or a private copy of the shadow history (for `folder` projects) at `~/.mensarium/projects/<project_id>/wt/<task_id>` on whichever device runs the chat (the **executor**, see below). The chat's branch is named `mensarium/<slug>-<task_id[-4:]>`, where `<slug>` is derived from the first message (or `chat` if there isn't one).

For a `repo` project you can instead start a chat **without a workspace**: the agent works directly in the project's own folder on its source device — the same checkout you use — with no branch of its own, no end-of-turn commits, and no Changes panel. This requires the source device's client to report the `inplace` capability; an outdated client falls back to a normal workspace chat from the main branch. A chat without a workspace can only run on the project's source device, never on another executor.

In the web UI, opening **New chat** in a `repo` project shows a "Create a workspace" toggle plus a branch picker; toggling it off switches to the in-place mode. Programmatically, `POST /v1/tasks` takes `project_id`, `workspace` (default `true`), `base` (branch to start a new workspace branch from), and `branch` (explicit name for the new branch instead of the auto-generated slug); `base`/`branch` are rejected for `folder` projects and for `workspace: false`.

### Base branch

For a `repo` project, a new workspace branch starts from:
- the branch named in `base`, if given;
- otherwise the project's chosen default (`default_base`, set in project settings — `default` means "the repository's main branch", detected as `origin/HEAD`, else `main`, else `master`);
- for `folder` projects, always the current snapshot (there is no branch concept).

`GET /v1/projects/{id}/branches` lists the source device's branches (name, whether it's a remote-tracking branch, last commit time) plus which one is `default`; used by the branch picker.

## What happens after each turn

At the end of every agent turn, Core asks the executor device to commit the chat's worktree: all changes are staged and committed (secrets and files matched by `.mensariumignore` are excluded — see [Security](security.md)), with commit message `mensarium: <first line of your message>` unless the agent (or you) made its own commit with a different message during the turn. If nothing changed, no commit is made. The resulting head is recorded on the task (`head_sha`) and, when the Core mirror is enabled, shipped there as a git bundle so the branch survives even if the executor device later goes offline.

## Changes panel, diff and revert

A project chat with a workspace has a **Changes** panel (`GET /v1/tasks/{id}/changes[?path=...&scope=pending|committed]`) showing only the chat's own work: commits reachable from the branch's head that are not reachable from any other branch, tag, or remote, counted from the point where the branch was made (its base) — so rebasing the chat branch onto a fresher main, or merging main into it, does not pull those upstream changes into the panel.

The panel splits into:
- **Not committed** — working-tree changes plus any `mensarium: …` end-of-turn commits (they count as not yet committed for display purposes). A file here can be reverted (`POST /v1/tasks/{id}/changes/revert {"path": ...}`), which restores it to its last **committed** version.
- **Committed** — any commit with a message other than the automatic `mensarium: …` ones (made by the agent on request, or by you), with its own file list and diff on click; no revert button there.

This requires an updated client on the device running the chat; with an older client the panel shows the old undifferentiated view. `GET /v1/tasks/{id}/changes` returns `{"ready": false}` until the chat has a workspace (`base_sha` set).

## Project instructions and AGENTS.md / CLAUDE.md

**Project instructions** are free text (up to 20,000 characters) you set per project (`instructions` field, `PUT /v1/projects/{id}`); they are injected into every chat's system prompt as `## Project instructions from the user`, right after the harness's own project block.

Separately, `GET /v1/projects/{id}/docs` reads `AGENTS.md` and `CLAUDE.md` from the project's source folder (symlinks are skipped) so the web UI can show their size and content. These files are **not** put into the prompt by Core — the agent is told in its system prompt to read them itself from its worktree if present, the same way it would on a normal checkout.

## Sync and the Core mirror

Core keeps its own bare mirror of each project at `~/.mensarium/projects/<project_id>/mirror.git` ([src/core/mirror.py](../src/core/mirror.py)), used to hand a project to an executor other than its source device and to survive the source going offline. It requires `git` on the Core host and an updated client that reports the `bundle` capability; without either, syncing falls back to talking to the source device directly and features that need the mirror (an executor other than the source, offline delivery) are unavailable.

- The source device sends its snapshot and branches to Core as an incremental git bundle whenever it reconnects and, after that, every 10 minutes (or immediately after project creation/`sync`). Device refs land under `refs/devices/<target_id>/…` in the mirror; the project's own snapshot ref (`refs/mensarium/snapshot`) becomes `refs/devices/<target_id>/snapshot`.
- A chat's branch (`refs/heads/mensarium/…`) reaches the mirror only when its executor commits and publishes it after a turn.
- Branches the mirror has for chats whose **executor differs from the source** are queued and delivered back to the source device as soon as it is online, so the source ends up with the same `mensarium/<slug>-<id>` branch the chat worked on.

## Which device runs a chat (the executor)

Each project has a `source_target_id` (the device holding the real folder or, for a `git_url` project, Core's own device holding the clone) and, optionally, a `default_executor_id` you can set explicitly in project settings. When a chat is created without naming a target device, Core picks the **executor**:

1. `default_executor_id`, if set.
2. Otherwise, Core's own built-in device, but only if it is online, supports running project chats, and its mirror already has the source's snapshot (so it isn't starting from nothing).
3. Otherwise, the source device itself.

Running a chat on a device other than the source requires that device to report both the `bundle` and `executor` capabilities. On the executor, a `repo` project's worktrees are created from a bare `repo.git` seeded with objects fetched from the Core mirror rather than from a live checkout.

## Where files live on disk

All paths below are under `~/.mensarium/projects/` (or `$MENSARIUM_HOME/projects/` if that env var is set), on the relevant machine:

| Path | Where | What |
|---|---|---|
| `<id>/src/` | source device (Core's own device, for a `git_url` project) | the clone, for a project created from a git URL |
| `<id>/shadow.git` | source device | hidden bare history for a `folder` project |
| `<id>/repo.git` | an executor device that is not the source | bare copy the executor's worktrees branch off |
| `<id>/wt/<task_id>/` | executor device | one chat's working copy (workspace) |
| `<id>/mirror.git` | Core host | Core's own bare mirror of the project |
| `core-inbox/`, `inbox/` | Core host / client device | temporary storage for incoming git bundle chunks |

## Limitations

- A chat without a workspace only works for `repo` projects, and only on the project's source device.
- Size limits: a project snapshot fails if the folder exceeds `size_limit_mb` (default 1024 MB); individual files above `file_limit_mb` (default 100 MB) are skipped and listed as `skipped` on the project.
- `.mensariumignore` at the source folder's root can exclude extra paths from `folder`-kind snapshots, the same way `.gitignore` would; files matching secret patterns (`.env`, keys, `.ssh`, credential files — see [Security](security.md)) are always excluded and cannot be re-included.
- Reading the source folder, and delivering a chat branch back to a device that isn't currently online, both wait for that device to reconnect; the project or chat shows an error/pending state until then.
