.PHONY: dev lint test schemas core target dist

DIST_URL ?= https://mensarium.com
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' src/__init__.py)

# hatch cannot install src/ as `mensarium` in editable mode, so dev mode links it through .dev/
dev:
	uv venv --allow-existing --python 3.12 .venv
	uv pip uninstall --python .venv/bin/python mensarium 2>/dev/null || true
	uv pip install --python .venv/bin/python -r pyproject.toml ruff mypy types-PyYAML
	mkdir -p .dev && ln -sfn ../src .dev/mensarium
	echo "$(CURDIR)/.dev" > "$$(.venv/bin/python -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')/mensarium-dev.pth"
	printf '#!/bin/sh\nexec "$$(dirname "$$0")/python" -m mensarium "$$@"\n' > .venv/bin/mensarium && chmod +x .venv/bin/mensarium

lint:
	.venv/bin/ruff check src
	MYPYPATH=.dev .venv/bin/mypy -p mensarium

test: lint
	.venv/bin/python -m unittest discover -s tests -v

schemas:
	.venv/bin/python -c "from pathlib import Path; from mensarium.contracts.schemas import export; export(Path('schemas'))"

core:
	.venv/bin/mensarium core serve

target:
	.venv/bin/mensarium target run

dist:
	@test -z "$$(git status --porcelain --untracked-files=no)" || (echo "commit changes before make dist" && exit 1)
	mkdir -p dist
	git archive --format=tar.gz --prefix=mensarium/ -o dist/mensarium-$(VERSION).tar.gz HEAD
	cp dist/mensarium-$(VERSION).tar.gz dist/mensarium.tar.gz
	sed 's|^MENSARIUM_SOURCE_DEFAULT=""|MENSARIUM_SOURCE_DEFAULT="$(DIST_URL)/dist/mensarium.tar.gz"|' install.sh > dist/install.sh
	printf '{"version": "%s", "file": "mensarium-%s.tar.gz", "sha256": "%s"}\n' $(VERSION) $(VERSION) $$(shasum -a 256 dist/mensarium.tar.gz | cut -d' ' -f1) > dist/latest.json
	.venv/bin/python -c "from mensarium.plugins import export_index; export_index('dist/plugins.json')"
