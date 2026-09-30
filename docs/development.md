# Development

Working on Mensarium itself: setting up a dev environment, running Core and a client locally, linting, testing, building schemas and the release archive, and how releases are published.

## Prerequisites

- [uv](https://docs.astral.sh/uv/)
- Python 3.12 (uv installs it into the project's `.venv` if it isn't already available; `requires-python = ">=3.12"` in `pyproject.toml`)

## Set up the environment

```sh
make dev
```

This creates `.venv` with `uv venv --python 3.12`, installs the project's dependencies plus `ruff`, `mypy` and `types-PyYAML`, and then links the source tree in so it can be imported as the `mensarium` package:

```sh
mkdir -p .dev && ln -sfn ../src .dev/mensarium
echo "$(pwd)/.dev" > <site-packages>/mensarium-dev.pth
```

`src/` cannot be installed by hatch as an editable `mensarium` package directly (the wheel build renames `src` to `mensarium` at build time, which hatch's editable mode doesn't support), so `make dev` works around it with a symlink (`.dev/mensarium -> ../src`) plus a `.pth` file that adds `.dev` to `sys.path`. `make dev` also writes `.venv/bin/mensarium` as a small wrapper script that runs `python -m mensarium`. Because of this, `mypy` needs `MYPYPATH=.dev` to resolve the `mensarium` package (see `make lint` below).

## Run Core and a client locally

Use a throwaway `MENSARIUM_HOME` so this never touches your real `~/.mensarium`; `mensarium_home()` ([src/shared/paths.py](../src/shared/paths.py)) reads the `MENSARIUM_HOME` environment variable (falling back to `~/.mensarium`), and every CLI command and path in Core and the client derives from it.

Core, in one terminal:

```sh
export MENSARIUM_HOME=/tmp/mensarium-core-dev
.venv/bin/mensarium core        # first run: interactive setup wizard (network, LLM provider, this host as a device)
.venv/bin/mensarium core serve  # foreground; --host/--port override the configured ones
```

A client, in another terminal, pointed at that Core (get a pairing code from the first terminal with `mensarium core pair-code`, or from the web UI under Devices):

```sh
export MENSARIUM_HOME=/tmp/mensarium-client-dev
.venv/bin/mensarium client pair --server http://127.0.0.1:8787 --code <code> --root /tmp/mensarium-client-dev/work
.venv/bin/mensarium client run           # worker: executes tool calls, foreground
.venv/bin/mensarium client gateway run   # gateway: local web UI for this client, foreground (separate terminal)
```

`client pair` also takes `--full-access/--no-full-access`, `--remote-update/--no-remote-update`, `--remote-plugins/--no-remote-plugins` and `--shell/--no-shell` to configure the device's policy non-interactively.

For a fully scripted throwaway Core with a mock LLM, three clients and seeded data (used to generate the screenshots on the landing page), see [landing/stand/README.md](../landing/stand/README.md) — it never touches `~/.mensarium` either, keeping everything under `$MENSARIUM_STAND` (`/tmp/mensarium-stand` by default).

## Lint

```sh
make lint
```

Runs `ruff check src` and `MYPYPATH=.dev mypy -p mensarium`. Ruff config (`pyproject.toml`): line length 120, `target-version = "py312"`, rule sets `E`, `F`, `I`, `B`, `UP`, `SIM` (with `E501`, `SIM105`, `B008` ignored), first-party import group `mensarium`. Mypy: `python_version = "3.12"`, `ignore_missing_imports = true`.

## Test

```sh
make test
```

Runs `make lint` first, then `python -m unittest discover -s tests -v`. This is the same command CI runs (`.github/workflows/release.yml`). Tests live in `tests/*.py`, one file per feature area (backup/move, attachments, plugin OAuth, projects, mirror, secrets, push, streaming, instructions, ...).

`tests/` also has two browser-side files that `make test` does **not** run and that CI does not run either:

- `tests/chat-progress.test.mjs` — plain Node, no framework: it loads `src/web/app.js`'s source, extracts the chat event handler with `node:vm`, and asserts against it with `node:assert/strict`. Run with `node tests/chat-progress.test.mjs`.
- `tests/plan-strip.browser.mjs` — same idea but renders the extracted component in a real headless browser via Playwright (`chromium.launch`). Needs Playwright installed; point `PLAYWRIGHT_MODULE` at it if it isn't importable as `playwright` directly. Run with `node tests/plan-strip.browser.mjs`.

Run these manually after changing `src/web/app.js`'s chat rendering or plan-strip component.

## Schemas

```sh
make schemas
```

Exports one `<name>.schema.json` per contract model (`mensarium.contracts.schemas.export`, see [Architecture](architecture.md#json-schemas)) into `schemas/`. Any change to a model in `src/contracts/` should be followed by re-running this and reviewing the diff, together with its contract test in `tests/`.

## Build the release archive

```sh
make dist
```

Refuses to run with uncommitted changes to tracked files (`git status --porcelain --untracked-files=no` must be empty). Produces, from `HEAD`:

- `dist/mensarium-<version>.tar.gz` — `git archive` of the repo, prefixed `mensarium/`
- `dist/mensarium.tar.gz` — a copy of the same archive at a stable name
- `dist/install.sh` — the installer with `MENSARIUM_SOURCE_DEFAULT` pointed at `$DIST_URL/dist/mensarium.tar.gz` (`DIST_URL` defaults to `https://mensarium.com`)
- `dist/latest.json` — `{version, file, sha256}` of the archive
- `dist/plugins.json` — the plugin catalog index

## The website

```sh
make site-serve   # serves landing/ on http://localhost:8800 for local preview
make site          # builds dist/site/ for deployment (a copy of landing/ minus landing/stand/)
```

Both first run `site-vendor`, which copies the product's own CSS/JS/fonts (`src/web/styles.css`, `orb.js`, favicon, fonts) into `landing/vendor/` so the landing page can reuse the same look without depending on a running Core. The screenshot stand under `landing/stand/` is excluded from `make site`'s output; see [landing/stand/README.md](../landing/stand/README.md) for how it captures the screenshots used on the landing page and in `README.md`.

## Release process

1. Bump `__version__` in [src/__init__.py](../src/__init__.py).
2. Add an entry to `CHANGELOG.md` under a new `## <version>` heading.
3. Push to `main`.

GitHub Actions (`.github/workflows/release.yml`) then runs `make dev` and `make test` on every push to `main` and every pull request. On a push to `main` (not a PR), it additionally reads the version from `src/__init__.py`: if a git tag `v<version>` doesn't already exist on the remote, it runs `make dist`, publishes the archive and installer to the deploy server, tags the commit `v<version>` and cuts a GitHub release with notes taken from that version's `CHANGELOG.md` section. If the tag already exists, those steps are skipped with a note in the job summary. The site is republished on every push to `main`, whether or not a new version was released.

Do not push tags manually — the workflow's own version check is what decides whether to build and publish, and a tag that already exists on the remote makes it skip that commit's release entirely.
