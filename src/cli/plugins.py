"""`mensarium plugins` and `mensarium mcp`: manage plugins of the Core running on this machine through its API."""

import json
from pathlib import Path
from typing import Annotated, Any

import httpx
import questionary
import typer
from rich.table import Table

from mensarium.cli.ui import console, fail, ok, warn
from mensarium.core.config import CorePaths, load_config, read_secret
from mensarium.target.config import TargetPaths

plugins_app = typer.Typer(help="Plugins: device tools, Core tools and MCP servers", no_args_is_help=True)
mcp_app = typer.Typer(help="MCP servers (each one is a plugin)", no_args_is_help=True)

RISKS = ("read", "execute", "write", "network", "destructive")


class ApiError(Exception):
    pass


def _api(method: str, path: str, body: Any = None, content: bytes | None = None) -> Any:
    paths = CorePaths()
    if not paths.config.exists():
        raise ApiError("the Core is not installed on this machine; run this on the Core host")
    cfg = load_config(paths)
    token = read_secret(paths, "secret://admin-token") or ""
    headers = {"Authorization": f"Bearer {token}"}
    if content is not None:
        headers["Content-Type"] = "text/plain"
    try:
        resp = httpx.request(
            method, f"http://127.0.0.1:{cfg.server.port}{path}", json=body, content=content, headers=headers, timeout=300
        )
    except httpx.ConnectError as e:
        raise ApiError("the Core is not running; start it with `mensarium service restart core`") from e
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail")
        except ValueError:
            detail = resp.text
        raise ApiError(str(detail))
    return resp.json() if resp.content else None


def _run(method: str, path: str, body: Any = None, content: bytes | None = None) -> Any:
    try:
        return _api(method, path, body, content)
    except ApiError as e:
        fail(str(e))
        raise typer.Exit(1) from e


def _text(value: Any) -> str:
    return value if isinstance(value, str) else (value or {}).get("en") or next(iter((value or {}).values()), "")


def _kind(p: dict[str, Any]) -> str:
    parts = []
    if p["provides"]["device_tools"]:
        parts.append(f"device tools: {len(p['provides']['device_tools'])}")
    if p["provides"]["core_tools"]:
        parts.append(", ".join(p["provides"]["core_tools"]))
    if p["provides"]["mcp"]:
        parts.append("mcp")
    return ", ".join(parts)


def _state(p: dict[str, Any], devices: dict[str, str]) -> str:
    if not p["installed"]:
        return "[dim]not installed[/dim]"
    if not p["installed"]["enabled"]:
        return "[dim]off[/dim]"
    if p["missing"]:
        return f"[yellow]needs {', '.join(k.lstrip('_') for k in p['missing'])}[/yellow]"
    status = p.get("status") or {}
    if not p["provides"]["mcp"]:
        return "[green]on[/green]"
    where = "core" if p["placement"] == "core" else devices.get(p["placement"] or "", p["placement"] or "?")
    tools = len(status.get("tools") or [])
    if status.get("state") == "ok":
        return f"[green]on[/green] · {where} · {tools} tools"
    if status.get("state") == "error":
        return f"[red]error[/red] · {where} · {status.get('error', '')[:60]}"
    return f"{status.get('state', '?')} · {where}"


@plugins_app.command("list")
def plugins_list(
    catalog: Annotated[bool, typer.Option("--catalog", help="Show the whole catalog, not only installed plugins")] = False,
    as_json: Annotated[bool, typer.Option("--json", help="Print JSON")] = False,
) -> None:
    """List installed plugins (or the whole catalog)."""
    data = _run("GET", "/v1/plugins")
    items = [p for p in data["items"] if catalog or p["installed"]]
    if as_json:
        console.print_json(json.dumps(items, ensure_ascii=False))
        return
    devices = {d["id"]: d["name"] for d in data["devices"]}
    table = Table(box=None, header_style="dim")
    for col in ("id", "name", "version", "category", "provides", "state"):
        table.add_column(col)
    for p in items:
        version = p["installed"]["version"] if p["installed"] else p["version"]
        if p["update"]:
            version += f" → {p['version']}"
        table.add_row(p["id"], _text(p["name"]), version, p.get("category") or "other", _kind(p), _state(p, devices))
    console.print(table if items else "No plugins installed. See the catalog: mensarium plugins list --catalog")
    if data.get("error"):
        warn(data["error"])


@plugins_app.command("info")
def plugins_info(plugin_id: str) -> None:
    """Show a plugin: what it adds, its settings and status."""
    p = _run("GET", f"/v1/plugins/{plugin_id}")
    devices = {d["id"]: d["name"] for d in _run("GET", "/v1/plugins")["devices"]}
    console.print(f"[bold]{_text(p['name'])}[/bold] {p['version']} · {p.get('author') or ''}")
    console.print(_text(p["description"]) or _text(p["summary"]))
    console.print(f"provides: {_kind(p)}")
    console.print(f"state: {_state(p, devices)}")
    if p.get("mcp"):
        m = p["mcp"]
        target = m.get("url") or " ".join([m.get("command") or "", *m.get("args", [])])
        console.print(f"mcp: {m['transport']} {target} · risk {p['risk']}")
    if p["settings"]:
        table = Table(box=None, header_style="dim")
        for col in ("setting", "value", "notes"):
            table.add_column(col)
        for key, spec in p["settings"].items():
            value = p["config"].get(key)
            shown = ("set" if value.get("set") else "[yellow]not set[/yellow]") if spec.get("secret") else json.dumps(value, ensure_ascii=False)
            notes = " · ".join(x for x in ["secret" if spec.get("secret") else "", "required" if spec.get("required") else "", _text(spec.get("help"))] if x)
            table.add_row(key, shown, notes)
        console.print(table)
    tools = (p.get("status") or {}).get("tools") or []
    if tools:
        disabled = set(p.get("disabled_tools") or [])
        console.print("tools: " + ", ".join(f"[dim]{t['name']} (off)[/dim]" if t["name"] in disabled else t["name"] for t in tools))


@plugins_app.command("install")
def plugins_install(source: Annotated[str, typer.Argument(help="Catalog id or a path to a plugin manifest (.yaml)")]) -> None:
    """Install a plugin from the catalog or from a YAML manifest."""
    path = Path(source)
    if path.suffix in (".yaml", ".yml", ".json") and path.exists():
        p = _run("POST", "/v1/plugins/custom", content=path.read_bytes())
    else:
        p = _run("POST", "/v1/plugins", {"id": source})
    ok(f"Installed {p['id']} {p['version']}")
    if p["missing"]:
        warn(f"Configure it: mensarium plugins config {p['id']} " + " ".join(f"--secret {k}" if (p["settings"].get(k) or {}).get("secret") else f"{k.lstrip('_')}=..." for k in p["missing"]))


@plugins_app.command("update")
def plugins_update(plugin_id: str) -> None:
    """Update a plugin to the catalog version."""
    p = _run("POST", f"/v1/plugins/{plugin_id}/update")
    ok(f"{p['id']} is now {p['version']}")


@plugins_app.command("remove")
def plugins_remove(plugin_id: str, yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask")] = False) -> None:
    """Remove a plugin and its secrets."""
    if not yes and not questionary.confirm(f"Remove {plugin_id} and its secrets?", default=False).ask():
        raise typer.Exit(1)
    _run("DELETE", f"/v1/plugins/{plugin_id}")
    ok(f"Removed {plugin_id}")


@plugins_app.command("enable")
def plugins_enable(plugin_id: str) -> None:
    """Turn a plugin on."""
    _run("PATCH", f"/v1/plugins/{plugin_id}", {"enabled": True})
    ok(f"{plugin_id} is on")


@plugins_app.command("disable")
def plugins_disable(plugin_id: str) -> None:
    """Turn a plugin off (settings are kept)."""
    _run("PATCH", f"/v1/plugins/{plugin_id}", {"enabled": False})
    ok(f"{plugin_id} is off")


@plugins_app.command("config")
def plugins_config(
    plugin_id: str,
    settings: Annotated[list[str] | None, typer.Argument(help="KEY=VALUE pairs")] = None,
    secret: Annotated[list[str] | None, typer.Option("--secret", help="Secret setting to enter (asked without echo)")] = None,
    clear_secret: Annotated[list[str] | None, typer.Option("--clear-secret", help="Secret setting to delete")] = None,
    placement: Annotated[str | None, typer.Option("--placement", help="Where the MCP server runs: core or a device name")] = None,
    risk: Annotated[str | None, typer.Option("--risk", help=f"Risk of the plugin's tools: {', '.join(RISKS)}")] = None,
) -> None:
    """Change plugin settings; without arguments shows them."""
    values: dict[str, str] = {}
    for item in settings or []:
        key, sep, value = item.partition("=")
        if not sep:
            fail(f"expected KEY=VALUE, got {item!r}")
            raise typer.Exit(2)
        values[key.strip()] = value
    secrets: dict[str, str | None] = {k: None for k in clear_secret or []}
    for key in secret or []:
        value = questionary.password(f"{key}:").ask()
        if not value:
            fail(f"{key} is empty")
            raise typer.Exit(1)
        secrets[key] = value
    if not (values or secrets or placement or risk):
        plugins_info(plugin_id)
        return
    body = {"values": values, "secrets": secrets, "placement": placement, "risk": risk}
    p = _run("PUT", f"/v1/plugins/{plugin_id}/config", body)
    ok(f"{plugin_id} configured" + (f"; still needs {', '.join(p['missing'])}" if p["missing"] else ""))


@plugins_app.command("probe")
def plugins_probe(plugin_id: str) -> None:
    """Restart the plugin's MCP server now and show its tools."""
    with console.status(f"Connecting {plugin_id}..."):
        p = _run("POST", f"/v1/plugins/{plugin_id}/probe")
    status = p.get("status") or {}
    if status.get("state") == "ok":
        ok(f"{plugin_id}: {len(status.get('tools', []))} tools")
        for t in status.get("tools", []):
            console.print(f"  {t['name']}  [dim]{t.get('description', '')[:90]}[/dim]")
    else:
        fail(f"{plugin_id}: {status.get('state')} {status.get('error', '')}")
        raise typer.Exit(1)


# ---- mcp ----------------------------------------------------------------------


@mcp_app.command("list")
def mcp_list() -> None:
    """List MCP servers."""
    data = _run("GET", "/v1/plugins")
    devices = {d["id"]: d["name"] for d in data["devices"]}
    items = [p for p in data["items"] if p["installed"] and p["provides"]["mcp"]]
    table = Table(box=None, header_style="dim")
    for col in ("server", "plugin", "runs", "risk", "state"):
        table.add_column(col)
    for p in items:
        m = p.get("mcp") or {}
        runs = m.get("url") or " ".join([m.get("command") or "", *m.get("args", [])])
        table.add_row(p["server"], p["id"], runs[:60], p["risk"], _state(p, devices))
    console.print(table if items else "No MCP servers. Add one: mensarium mcp add NAME --command 'npx -y ...' or --url URL")


def _pairs(items: list[str] | None, what: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for item in items or []:
        key, sep, value = item.partition("=")
        if not sep:
            fail(f"expected {what} as KEY=VALUE, got {item!r}")
            raise typer.Exit(2)
        out[key] = value
    return out


@mcp_app.command("add")
def mcp_add(
    name: Annotated[str, typer.Argument(help="Short name: lowercase letters, digits and dashes")],
    command: Annotated[str | None, typer.Option("--command", help="Command line of a stdio server, e.g. 'npx -y pkg'")] = None,
    url: Annotated[str | None, typer.Option("--url", help="URL of a streamable HTTP server")] = None,
    env: Annotated[list[str] | None, typer.Option("--env", help="Environment variable KEY=VALUE")] = None,
    secret_env: Annotated[list[str] | None, typer.Option("--secret-env", help="Secret environment variable KEY (asked without echo)")] = None,
    header: Annotated[list[str] | None, typer.Option("--header", help="HTTP header KEY=VALUE")] = None,
    secret_header: Annotated[list[str] | None, typer.Option("--secret-header", help="Secret HTTP header KEY (asked without echo)")] = None,
    device: Annotated[str | None, typer.Option("--device", help="Run on this device instead of the Core")] = None,
    risk: Annotated[str, typer.Option("--risk", help=f"Risk of its tools: {', '.join(RISKS)}")] = "network",
    description: Annotated[str, typer.Option("--description", help="What the server is for")] = "",
) -> None:
    """Add an MCP server that runs in the Core or on a device."""
    if bool(command) == bool(url):
        fail("pass either --command (stdio) or --url (http)")
        raise typer.Exit(2)
    secrets_env = {k: questionary.password(f"{k}:").ask() or "" for k in secret_env or []}
    secrets_headers = {k: questionary.password(f"{k}:").ask() or "" for k in secret_header or []}
    body = {
        "name": name,
        "transport": "stdio" if command else "http",
        "command": command,
        "url": url,
        "env": _pairs(env, "--env"),
        "secret_env": secrets_env,
        "headers": _pairs(header, "--header"),
        "secret_headers": secrets_headers,
        "placement": device or "core",
        "risk": risk,
        "description": description,
    }
    with console.status(f"Adding {name}..."):
        p = _run("POST", "/v1/plugins/mcp", body)
    ok(f"Added MCP server {p['server']} as plugin {p['id']}; check it with: mensarium mcp probe {name}")


def _mcp_id(name: str) -> str:
    return name if name.startswith("mcp-") else f"mcp-{name}"


@mcp_app.command("remove")
def mcp_remove(name: str, yes: Annotated[bool, typer.Option("--yes", "-y", help="Do not ask")] = False) -> None:
    """Remove an MCP server."""
    plugins_remove(_mcp_id(name), yes)


@mcp_app.command("probe")
def mcp_probe(name: str) -> None:
    """Connect to an MCP server now and list its tools."""
    plugins_probe(_mcp_id(name))


@mcp_app.command("tools")
def mcp_tools(
    name: str,
    disable: Annotated[list[str] | None, typer.Option("--disable", help="Hide a tool from the agent")] = None,
    enable: Annotated[list[str] | None, typer.Option("--enable", help="Show a hidden tool again")] = None,
) -> None:
    """Show an MCP server's tools or hide some of them from the agent."""
    pid = _mcp_id(name)
    p = _run("GET", f"/v1/plugins/{pid}")
    hidden = set(p.get("disabled_tools") or [])
    if disable or enable:
        hidden = (hidden | set(disable or [])) - set(enable or [])
        p = _run("PUT", f"/v1/plugins/{pid}/config", {"disabled_tools": sorted(hidden)})
    for t in (p.get("status") or {}).get("tools", []):
        mark = "[dim]off[/dim]" if t["name"] in hidden else "[green]on[/green]"
        console.print(f"{mark}  {t['name']}  [dim]{t.get('description', '')[:80]}[/dim]")


def target_plugins() -> None:
    """MCP servers the Core placed on this device, as of the last sync."""
    path = TargetPaths().plugins
    if not path.exists():
        console.print("No MCP servers on this device.")
        return
    for s in json.loads(path.read_text()):
        mark = "[green]ok[/green]" if s["state"] == "ok" else f"[red]{s['state']}[/red]"
        console.print(f"{mark}  {s['name']}  {len(s.get('tools', []))} tools  [dim]{s.get('error', '')}[/dim]")
