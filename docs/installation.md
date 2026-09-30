# Installation

This page covers the install script, what it puts where, updating and uninstalling. For setting up Core or a client after installing, see [Core](core.md) and [Clients](clients.md).

## Supported platforms

macOS and Linux (`uname -s` must report `Darwin` or `Linux`). Any CPU architecture `uname -m` reports is accepted; the script installs Python 3.12 itself through [uv](https://docs.astral.sh/uv/), so you don't need Python preinstalled.

## Prerequisites

- `tar`
- `curl` or `wget` (to fetch the installer and, if needed, `uv`)
- `git`, only if you install from a git URL

## Install

```sh
curl -fsSL https://mensarium.com/install.sh | sh
```

This installs the `mensarium` command; it does not start or configure anything. Next step on the machine: [`mensarium core`](core.md) or [`mensarium client`](clients.md).

## What the script does

1. Detects the OS (`Darwin`/`Linux`) and checks for `tar`.
2. Resolves a source to install from (see below) and puts it at `$MENSARIUM_HOME/src` — a local checkout copies just `pyproject.toml`, `install.sh` and `src` (and `README.md` if present); a git clone or tarball is extracted whole.
3. Installs `uv` into `$MENSARIUM_HOME/bin` if it isn't already on `PATH` or there.
4. Creates a Python 3.12 virtualenv at `$MENSARIUM_HOME/venv` with `uv venv`.
5. Installs the `mensarium` package into that venv from `$MENSARIUM_HOME/src` with `uv pip install`.
6. Symlinks `$MENSARIUM_HOME/venv/bin/mensarium` into `$MENSARIUM_BIN_DIR`.

Nothing is asked interactively; all configuration happens later, in `mensarium core` or `mensarium client`.

## Source

By default the script fetches the released source from `mensarium.com`. You can point it elsewhere:

```sh
sh install.sh --source PATH_OR_URL
# or
MENSARIUM_SOURCE=PATH_OR_URL sh install.sh
```

`--source` (or `$MENSARIUM_SOURCE`) accepts:

- a local directory containing `pyproject.toml` (a checkout) — copied as-is
- a local `.tar.gz` file — extracted
- a git URL (ends in `.git` or starts with `git@`) — `git clone --depth 1`
- any other URL — fetched and extracted as a `.tar.gz`

Running `sh install.sh` directly from a checkout (i.e. the script's own directory has `pyproject.toml` and `src/__init__.py`) uses that checkout automatically, without `--source`.

## Environment variables

| Variable | Default | Effect |
|---|---|---|
| `MENSARIUM_HOME` | `~/.mensarium` | Where everything (venv, source, Core/client data) lives |
| `MENSARIUM_BIN_DIR` | `~/.local/bin` | Where the `mensarium` symlink is created |
| `MENSARIUM_SOURCE` | `https://mensarium.com/dist/mensarium.tar.gz` in the published script; the checkout itself when run from one | Directory, `.tar.gz` file, git URL or tarball URL to install from (same as `--source`) |
| `MENSARIUM_UPDATE_URL` | unset | Overrides the update server `mensarium update` checks, instead of `https://mensarium.com` (Core) or a client's paired Core |
| `MENSARIUM_SOURCE_DIR` | unset | Overrides the source directory Core serves at `/install.sh` and `/dist/mensarium.tar.gz` to clients, instead of `$MENSARIUM_HOME/src` |

If `$MENSARIUM_BIN_DIR` is not on `PATH`, the installer prints a warning with the line to add to your shell profile.

## Updating

```sh
mensarium update            # install the latest version and restart installed services
mensarium update --check    # only report whether a newer version exists
mensarium update --force    # reinstall even if the version is the same
mensarium version            # installed version, roles present on this machine, and whether an update is available
```

Where `mensarium update` looks:

- On a **Core** host: `https://mensarium.com`, or `$MENSARIUM_UPDATE_URL` if set.
- On a **client** with no Core on the same machine: the client's own paired Core (`server` in its config), so it always tracks the Core it's paired with.

`mensarium update` downloads `<source>/dist/mensarium.tar.gz`, verifies its `sha256` against `<source>/dist/latest.json`, reinstalls the package into the existing venv, and restarts any installed `core`/`client`/`gateway` service. It needs the `uv` that install.sh put in place; without it the update stops and asks you to re-run the installer.

The web UI can also trigger an update: Core updates a paired client remotely (`POST /v1/targets/{id}/update`) if the device allows it (`allow_remote_update`, set at pairing — see [Clients](clients.md)); every paired device also gets a built-in automation that checks and updates it every two hours (see [Automations](automations.md)). The Core host's own built-in device cannot be remotely updated this way — it updates together with Core.

## Uninstalling

```sh
mensarium uninstall            # stop and remove installed services (core, client, gateway)
mensarium uninstall --purge    # also delete ~/.mensarium (data, keys, venv) after confirming
```

or, without an existing `mensarium` command:

```sh
sh install.sh uninstall
```

which runs `mensarium uninstall --purge` from the installed venv if one is found, and does nothing otherwise.
