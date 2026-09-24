.PHONY: dev lint test schemas core target dist

DIST_URL ?= https://mensarium.com

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
	mkdir -p dist
	git archive --format=tar.gz --prefix=mensarium/ -o dist/mensarium.tar.gz HEAD
	sed 's|^MENSARIUM_SOURCE_DEFAULT=""|MENSARIUM_SOURCE_DEFAULT="$(DIST_URL)/dist/mensarium.tar.gz"|' install.sh > dist/install.sh
