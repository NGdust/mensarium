"""`mensarium projects`: folders and git repositories the agent works on in isolated copies, through the Core's API."""

import time
from pathlib import Path, PurePath
from typing import Annotated, Any

import questionary
import typer
from rich.markup import escape
from rich.table import Table

from mensarium.cli.plugins import ApiError, _run
from mensarium.cli.ui import console, fail, ok, warn

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


@projects_app.command("init")
def projects_init(
    path: Annotated[Path | None, typer.Argument(help="Folder to register (default: the current folder)")] = None,
    name: Annotated[str | None, typer.Option(help="Project name (default: the folder name)")] = None,
) -> None:
    """Register a folder on this machine as a project: the Core reads it and chats run from its snapshot."""
    from mensarium.cli.plugins import api_base_url, api_target_id

    folder = (path or Path.cwd()).expanduser().resolve()
    if not folder.is_dir():
        fail(f"{folder} is not a folder")
        raise typer.Exit(1)
    _ensure_root(folder)
    try:
        target_id = api_target_id()
    except ApiError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    if not target_id:
        fail("this machine is not a device of the Core: pair it with `mensarium client`, or turn on the Core's own device")
        raise typer.Exit(1)
    p = _run("POST", "/v1/projects", {"name": name or folder.name, "source_target_id": target_id, "source_path": str(folder)})
    console.print(f"Reading {escape(str(folder))}...")
    deadline = time.monotonic() + 600
    while p["status"] == "creating" or p["syncing"]:
        if time.monotonic() > deadline:
            fail("the Core is still reading the folder; check `mensarium projects list` later")
            raise typer.Exit(1)
        time.sleep(2)
        p = _run("GET", f"/v1/projects/{p['id']}")
    if p["status"] == "error" or p.get("error"):
        fail(p.get("error") or "the Core could not read the folder")
        raise typer.Exit(1)
    ok(f"Project {escape(p['name'])} ({p['kind_label']}) is ready: {api_base_url()}/#/projects/{p['id']}")


def _ensure_root(folder: Path) -> None:
    """A project must lie inside the device's allowed folders; on a client the user may add one here."""
    from mensarium.cli import service
    from mensarium.client.config import ClientPaths, load_client_config, save_client_config
    from mensarium.core.config import CorePaths, load_config
    from mensarium.core.device import device_roots

    core, client = CorePaths(), ClientPaths()
    if core.config.exists():
        roots = [Path(r) for r in device_roots(load_config(core))]
        if not any(folder.is_relative_to(r) for r in roots):
            fail(f"{folder} is outside the Core device's folders ({', '.join(map(str, roots))}); add it with `mensarium core setup`")
            raise typer.Exit(1)
        return
    if not client.config.exists():
        return
    cfg = load_client_config(client)
    if any(folder.is_relative_to(Path(r).expanduser().resolve()) for r in cfg.roots):
        return
    if not questionary.confirm(f"{folder} is outside this device's folders. Add it?", default=True).ask():
        raise typer.Exit(1)
    cfg.roots.append(str(folder))
    save_client_config(client, cfg)
    if service.is_installed("client"):
        service.restart("client")
        console.print("Client restarted with the new folder; waiting for it to reconnect...")
        time.sleep(5)
    else:
        warn("Restart `mensarium client run` so the Core sees the new folder")


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
