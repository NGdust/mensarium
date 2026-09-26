"""`mensarium projects`: folders and git repositories the agent works on in isolated copies, through the Core's API."""

from pathlib import PurePath
from typing import Annotated, Any

import questionary
import typer
from rich.markup import escape
from rich.table import Table

from mensarium.cli.plugins import _run
from mensarium.cli.ui import console, fail, ok

projects_app = typer.Typer(help="Projects: folders and git repositories the agent works on in isolated copies", no_args_is_help=True)

_COLORS = {"ready": "green", "error": "red", "creating": "cyan", "syncing": "cyan"}


def _status(p: dict[str, Any]) -> str:
    status = "syncing" if p["syncing"] and p["status"] == "ready" else p["status"] or "-"
    color = _COLORS.get(status)
    return f"[{color}]{status}[/{color}]" if color else status


def _device(p: dict[str, Any]) -> str:
    name = escape(p["source_name"] or p["source_target_id"])
    return name if p["source_online"] else f"{name} [dim](offline)[/dim]"


@projects_app.command("list")
def projects_list() -> None:
    """List projects."""
    data = _run("GET", "/v1/projects")
    table = Table(box=None, header_style="dim")
    for col in ("id", "name", "kind", "device", "path", "status", "chats"):
        table.add_column(col)
    for p in data["items"]:
        table.add_row(
            p["id"], escape(p["name"]), p["kind"] or "-", _device(p), escape(p["source_path"]), _status(p), str(p["chats"] or 0)
        )
    console.print(table if data["items"] else "No projects. Create one with `mensarium projects create` or in the web UI.")


def _resolve_device(value: str) -> str:
    devices = _run("GET", "/v1/projects")["devices"]
    if any(d["id"] == value for d in devices):
        return value
    matches = [d for d in devices if d["name"] == value]
    if len(matches) > 1:
        fail(f"several devices are named {value}; use the device id")
        raise typer.Exit(1)
    if not matches:
        fail(f"unknown device {value}; known: {', '.join(sorted({d['name'] for d in devices})) or 'none'}")
        raise typer.Exit(1)
    return str(matches[0]["id"])


@projects_app.command("create")
def projects_create(
    device: Annotated[str | None, typer.Option(help="Device name or id with the folder")] = None,
    path: Annotated[str | None, typer.Option(help="Folder or git repository on the device")] = None,
    git: Annotated[str | None, typer.Option(help="Repository address to clone on the Core host")] = None,
    name: Annotated[str | None, typer.Option(help="Project name (default: the folder or repository name)")] = None,
) -> None:
    """Create a project from a folder on a device or from a git repository cloned on the Core host."""
    if git:
        repo = PurePath(git.rstrip("/").rsplit(":", 1)[-1]).name.removesuffix(".git")
        body: dict[str, Any] = {"name": name or repo or git, "git_url": git}
    elif device and path:
        if not path.startswith(("/", "~")):
            fail("--path must be absolute or start with ~")
            raise typer.Exit(1)
        body = {"name": name or PurePath(path).name or path, "source_target_id": _resolve_device(device), "source_path": path}
    else:
        fail("give --git URL, or --device and --path")
        raise typer.Exit(1)
    p = _run("POST", "/v1/projects", body)
    ok(f"Created project {p['id']}; {'cloning' if git else 'the device is reading the folder'}, check with `mensarium projects list`")


@projects_app.command("sync")
def projects_sync(project_id: str) -> None:
    """Read the project's source folder again."""
    _run("POST", f"/v1/projects/{project_id}/sync")
    ok(f"Syncing {project_id}")


@projects_app.command("delete")
def projects_delete(
    project_id: str,
    remove_shadow: Annotated[
        bool, typer.Option("--remove-shadow", help="Also delete the hidden version history of a folder project")
    ] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask")] = False,
) -> None:
    """Delete a project and its chats; files in the source folder are not touched."""
    if not yes and not questionary.confirm(f"Delete project {project_id} and its chats?", default=False).ask():
        raise typer.Exit(1)
    _run("DELETE", f"/v1/projects/{project_id}?remove_shadow={'true' if remove_shadow else 'false'}")
    ok("Removed")
