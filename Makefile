.PHONY: dev lint test schemas core target

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
