from importlib import resources
from pathlib import Path


def bundled_dir() -> Path:
    """Skills shipped with this release, one folder with SKILL.md per skill."""
    return Path(str(resources.files("mensarium.skills") / "catalog"))
