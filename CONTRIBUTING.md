# Contributing to Mensarium

Thanks for taking the time to help. This page covers the workflow; the technical details are in [docs/development.md](docs/development.md) and [docs/architecture.md](docs/architecture.md).

## Before you start

- For anything larger than a small fix, open an issue first and describe the problem and the change you have in mind. It saves both sides a rewrite.
- Security problems are not reported through issues; see [SECURITY.md](SECURITY.md).

## Setting up

You need [uv](https://docs.astral.sh/uv/) and macOS or Linux.

```sh
git clone https://github.com/NGdust/mensarium.git
cd mensarium
make dev    # .venv with Python 3.12 and the package linked from src/
make test   # ruff + mypy + unit tests, the same check CI runs
```

[docs/development.md](docs/development.md) explains how to run Core and a client locally without touching your real `~/.mensarium`.

## Making a change

- Keep the change focused on one thing. Unrelated refactoring goes into its own pull request.
- Follow the existing style: `ruff` and `mypy` must pass (`make lint`), type hints on parameters and return values.
- Respect the boundaries between Core, the model and clients described in [docs/security.md](docs/security.md). A change that lets the model pick a device, a folder or a risk level, or lets a client run an unsigned request, will not be accepted even if it works.
- A change to a message format in `src/contracts/` comes with its JSON Schema (`make schemas`) and a test.
- Add or extend a test for the rule you change. Prefer adding cases to an existing test over new test files.
- User-visible changes get an entry at the top of [CHANGELOG.md](CHANGELOG.md).

## Pull requests

- Branch from `main`; CI runs `make test` on every pull request.
- Commit messages are short, imperative and lowercase: `fix pairing code expiry check`.
- Describe what changed and how you checked it. For UI changes, attach a screenshot.
- Do not bump the version in `src/__init__.py`; releases are cut by the maintainers.
