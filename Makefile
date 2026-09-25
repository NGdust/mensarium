.PHONY: dev lint test schemas core target dist release

DIST_URL ?= https://mensarium.com
VERSION := $(shell sed -n 's/^__version__ = "\(.*\)"/\1/p' src/mensarium/__init__.py)

dev:
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -e . ruff mypy types-PyYAML

lint:
	.venv/bin/ruff check src
	.venv/bin/mypy src

test: lint

schemas:
	.venv/bin/python -c "from pathlib import Path; from mensarium.contracts.schemas import export; export(Path('schemas'))"

core:
	.venv/bin/mensarium core serve

target:
	.venv/bin/mensarium target run

dist:
	@test -z "$$(git status --porcelain)" || (echo "commit changes before make dist" && exit 1)
	mkdir -p dist
	git archive --format=tar.gz --prefix=mensarium/ -o dist/mensarium-$(VERSION).tar.gz HEAD
	cp dist/mensarium-$(VERSION).tar.gz dist/mensarium.tar.gz
	sed 's|^MENSARIUM_SOURCE_DEFAULT=""|MENSARIUM_SOURCE_DEFAULT="$(DIST_URL)/dist/mensarium.tar.gz"|' install.sh > dist/install.sh
	printf '{"version": "%s", "file": "mensarium-%s.tar.gz", "sha256": "%s"}\n' $(VERSION) $(VERSION) $$(shasum -a 256 dist/mensarium.tar.gz | cut -d' ' -f1) > dist/latest.json
	.venv/bin/python -c "from mensarium.plugins import export_index; export_index('dist/plugins.json')"

release: dist
	git tag -a v$(VERSION) -m "v$(VERSION)"
