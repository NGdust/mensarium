"""`mensarium secrets`: the user secrets of the Core running on this machine, through its API."""

from typing import Annotated

import questionary
import typer
from rich.table import Table

from mensarium.cli.plugins import _run
from mensarium.cli.ui import console, ok

secrets_app = typer.Typer(help="Secrets: API keys and tokens the agent uses by name without seeing them", no_args_is_help=True)


@secrets_app.command("list")
def secrets_list() -> None:
    """List secrets without their values."""
    table = Table(box=None, header_style="dim")
    for col in ("name", "description", "devices", "updated"):
        table.add_column(col)
    for s in _run("GET", "/v1/secrets")["items"]:
        table.add_row(s["name"], s["description"][:60], "all" if "*" in s["targets"] else ", ".join(s["targets"]), s["updated_at"][:16])
    console.print(table)


@secrets_app.command("set")
def secrets_set(
    name: str,
    description: Annotated[str | None, typer.Option("--description", "-d")] = None,
    target: Annotated[list[str] | None, typer.Option("--target", help="Device id; repeat for several; all devices by default")] = None,
) -> None:
    """Add or replace a secret; the value is read without echo."""
    value = questionary.password(f"Value of {name}:").ask()
    if not value:
        raise typer.Exit(1)
    existing = next((s for s in _run("GET", "/v1/secrets")["items"] if s["name"] == name), None)
    if existing and target is None:
        target = existing["targets"]
    if existing and description is None:
        description = existing["description"]
    _run("PUT", f"/v1/secrets/{name}", {"value": value, "description": description or "", "targets": target or ["*"]})
    ok(f"Saved secret {name}")


@secrets_app.command("rm")
def secrets_rm(name: str) -> None:
    """Delete a secret."""
    _run("DELETE", f"/v1/secrets/{name}")
    ok(f"Deleted secret {name}")
