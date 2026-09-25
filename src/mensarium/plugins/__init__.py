import json
from importlib import resources
from pathlib import Path

import yaml

from mensarium.contracts.plugins import Plugin


def bundled_catalog() -> list[Plugin]:
    """Packages shipped with this release; mensarium.com may publish newer ones."""
    folder = resources.files("mensarium.plugins") / "catalog"
    return [
        Plugin.model_validate(yaml.safe_load(f.read_text()))
        for f in sorted(folder.iterdir(), key=lambda f: f.name)
        if f.name.endswith(".yaml")
    ]


def export_index(out: str | Path) -> None:
    data = {"format": 2, "plugins": [e.model_dump(exclude_defaults=True) for e in bundled_catalog()]}
    Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n")
