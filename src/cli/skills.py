"""`mensarium skills`: the skills of the Core running on this machine, through its API."""

from pathlib import Path
from typing import Annotated, Any

import questionary
import typer
from rich.table import Table

from mensarium.cli.plugins import _run
from mensarium.cli.ui import console, fail, ok

skills_app = typer.Typer(help="Skills: SKILL.md instructions the agent loads for particular kinds of work", no_args_is_help=True)


def _state(s: dict[str, Any]) -> str:
    if not s["enabled"]:
        return "[dim]off[/dim]"
    parts = ["[green]on[/green]"]
    if s["always"]:
        parts.append("always")
    if s["os"]:
        parts.append("/".join(s["os"]))
    if s["requires_tools"]:
        parts.append("needs " + ", ".join(s["requires_tools"]))
    return " · ".join(parts)


@skills_app.command("list")
def skills_list() -> None:
    """List bundled skills and your own."""
    data = _run("GET", "/v1/skills")
    table = Table(box=None, header_style="dim")
    for col in ("name", "description", "source", "state"):
        table.add_column(col)
    for s in data["items"]:
        source = "yours" + (" (replaces bundled)" if s["shadows"] else "") if s["source"] == "user" else "bundled"
        table.add_row(s["name"], s["description"][:80], source, _state(s))
    console.print(table)
    console.print(f"[dim]Your skills live in {data['folder']}/<name>/SKILL.md[/dim]")


@skills_app.command("show")
def skills_show(name: str) -> None:
    """Print a skill's SKILL.md."""
    s = _run("GET", f"/v1/skills/{name}")
    typer.echo(s["text"], nl=False)


@skills_app.command("install")
def skills_install(source: Annotated[Path, typer.Argument(help="A SKILL.md file or a folder that contains one")]) -> None:
    """Add a skill from a SKILL.md file; it becomes one of your skills."""
    path = source / "SKILL.md" if source.is_dir() else source
    if not path.is_file():
        fail(f"{path} not found")
        raise typer.Exit(1)
    s = _run("POST", "/v1/skills/file", content=path.read_bytes())
    ok(f"Installed skill {s['name']}" + (" (it replaces the bundled one)" if s["shadows"] else ""))


@skills_app.command("enable")
def skills_enable(name: str) -> None:
    """Offer the skill to the agent."""
    _run("PATCH", f"/v1/skills/{name}", {"enabled": True})
    ok(f"{name} is on")


@skills_app.command("disable")
def skills_disable(name: str) -> None:
    """Hide the skill from the agent (the file is kept)."""
    _run("PATCH", f"/v1/skills/{name}", {"enabled": False})
    ok(f"{name} is off")


@skills_app.command("remove")
def skills_remove(name: str, yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask")] = False) -> None:
    """Delete one of your skills; a bundled skill with the same name is used again."""
    if not yes and not questionary.confirm(f"Delete your skill {name}?", default=False).ask():
        raise typer.Exit(1)
    _run("DELETE", f"/v1/skills/{name}")
    ok(f"Removed {name}")
