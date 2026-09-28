from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mensarium.shared.paths import write_private

FILES: dict[str, str] = {
    "AGENTS.md": "operating instructions: rules, priorities and how to work",
    "SOUL.md": "persona and tone",
    "IDENTITY.md": "the agent's name and style",
    "USER.md": "who the user is and their durable preferences",
}


class InstructionError(Exception):
    pass


class InstructionStore:
    """Markdown files the user edits in Settings; every chat gets them in the system prompt.

    Same set and meaning as the OpenClaw workspace files, minus MEMORY.md: Mensarium keeps memory as notes."""

    def __init__(self, folder: Path) -> None:
        self.folder = folder

    def path(self, name: str) -> Path:
        if name not in FILES:
            raise InstructionError(f"unknown instruction file {name!r}")
        return self.folder / name

    def read(self, name: str) -> str:
        path = self.path(name)
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""

    def view(self, name: str) -> dict[str, Any]:
        path = self.path(name)
        present = path.is_file()
        stat = path.stat() if present else None
        return {
            "name": name,
            "description": FILES[name],
            "content": self.read(name),
            "missing": not present,
            "size": stat.st_size if stat else 0,
            "updated_at": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat() if stat else None,
        }

    def all(self) -> list[dict[str, Any]]:
        return [self.view(name) for name in FILES]

    def save(self, name: str, content: str) -> dict[str, Any]:
        """An empty file is removed rather than kept, so the prompt block only lists files with text."""
        path = self.path(name)
        text = content.replace("\r\n", "\n").strip()
        if text:
            write_private(path, text + "\n")
        elif path.is_file():
            path.unlink()
        return self.view(name)

    def prompt_files(self) -> list[tuple[str, str, str]]:
        files = []
        for name, description in FILES.items():
            text = self.read(name).strip()
            if text:
                files.append((name, description, text))
        return files
