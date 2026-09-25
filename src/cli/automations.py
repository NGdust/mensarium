"""`mensarium automations`: tasks the agent runs on a schedule, through the Core's API."""

from typing import Annotated, Any

import questionary
import typer
from rich.markup import escape
from rich.table import Table

from mensarium.cli.plugins import _run
from mensarium.cli.ui import console, ok

automations_app = typer.Typer(help="Automations: tasks the agent runs on a schedule", no_args_is_help=True)

_COLORS = {"ok": "green", "error": "red", "timeout": "red", "lost": "red", "running": "cyan"}


def _status(status: str | None) -> str:
    if not status:
        return "-"
    color = _COLORS.get(status)
    return f"[{color}]{status}[/{color}]" if color else status


def _next(a: dict[str, Any]) -> str:
    if not a["enabled"]:
        reason = f" ({a['disabled_reason']})" if a.get("disabled_reason") else ""
        return f"[dim]off{reason}[/dim]"
    return a["next_run_at"] or "-"


@automations_app.command("list")
def automations_list() -> None:
    """List automations."""
    data = _run("GET", "/v1/automations")
    table = Table(box=None, header_style="dim")
    for col in ("id", "name", "schedule", "device", "next", "last"):
        table.add_column(col)
    for a in data["items"]:
        table.add_row(
            a["id"], escape(a["name"]), escape(a["schedule_text"]), escape(a["target_name"] or a["target_id"]), _next(a), _status(a["last_status"])
        )
    console.print(table if data["items"] else "No automations. Ask the agent to create one, or use the web UI.")


def _duration(ms: int | None) -> str:
    return f"{ms / 1000:.1f}s" if ms is not None else "-"


def _run_line(run: dict[str, Any]) -> str:
    if run["status"] == "ok" and not run.get("result"):
        return "no reply"
    text = run.get("result") or run.get("error") or ""
    return escape(text.splitlines()[0][:80]) if text else "-"


def _run_status(run: dict[str, Any]) -> str:
    if run["status"] == "running" and run.get("task_status") == "WAITING_APPROVAL":
        return "[yellow]waiting approval[/yellow]"
    return _status(run["status"])


@automations_app.command("show")
def automations_show(automation_id: str) -> None:
    """Show an automation and its recent runs."""
    a = _run("GET", f"/v1/automations/{automation_id}")
    state = "[green]on[/green]" if a["enabled"] else "[dim]off[/dim]" + (f" ({a['disabled_reason']})" if a.get("disabled_reason") else "")
    rows = [
        ("name", escape(a["name"])),
        ("schedule", escape(a["schedule_text"])),
        ("device", escape(a["target_name"] or a["target_id"])),
        ("mode", a["mode"]),
        ("model", a["model"] or "-"),
        ("timeout", f"{a['timeout_s']}s"),
        ("notify", "yes" if a["notify"] else "no"),
        ("state", state),
        ("created by", a["created_by"]),
        ("next run", a["next_run_at"] or "-"),
        ("last run", a["last_run_at"] or "-"),
        ("last error", escape(a["last_error"]) if a["last_error"] else "-"),
    ]
    width = max(len(k) for k, _ in rows)
    for k, v in rows:
        console.print(f"[dim]{k.ljust(width)}[/dim]  {v}")
    runs = a["runs"][:10]
    if runs:
        console.print()
        table = Table(box=None, header_style="dim")
        for col in ("started", "status", "duration", "result"):
            table.add_column(col)
        for r in runs:
            table.add_row(r["started_at"], _run_status(r), _duration(r.get("duration_ms")), _run_line(r))
        console.print(table)


@automations_app.command("run")
def automations_run(automation_id: str) -> None:
    """Run an automation now."""
    run = _run("POST", f"/v1/automations/{automation_id}/run")
    ok(f"Started run {run['id']}")


@automations_app.command("enable")
def automations_enable(automation_id: str) -> None:
    """Turn an automation on."""
    _run("POST", f"/v1/automations/{automation_id}/enable")
    ok(f"{automation_id} is on")


@automations_app.command("disable")
def automations_disable(automation_id: str) -> None:
    """Turn an automation off."""
    _run("POST", f"/v1/automations/{automation_id}/disable")
    ok(f"{automation_id} is off")


@automations_app.command("remove")
def automations_remove(
    automation_id: str, yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask")] = False
) -> None:
    """Delete an automation and its run history."""
    if not yes and not questionary.confirm(f"Delete automation {automation_id}?", default=False).ask():
        raise typer.Exit(1)
    _run("DELETE", f"/v1/automations/{automation_id}")
    ok("Removed")
