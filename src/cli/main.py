import asyncio
import shutil
import socket
import subprocess
import sys
from pathlib import Path
from typing import Annotated

import httpx
import questionary
import typer

from mensarium import __version__
from mensarium.cli import service
from mensarium.cli.automations import automations_app
from mensarium.cli.plugins import mcp_app, plugins_app, target_plugins
from mensarium.cli.skills import skills_app
from mensarium.cli.ui import console, fail, ok, summary, use_select_event_loop, warn
from mensarium.client.config import ClientConfig, ClientPaths, load_client_config
from mensarium.core.config import CorePaths, load_config
from mensarium.shared.logging import setup_logging
from mensarium.shared.paths import mensarium_home

app = typer.Typer(help="Mensarium: portable agent harness (Core + clients)", no_args_is_help=True)
core_app = typer.Typer(help="Main agent (Core) commands", no_args_is_help=True)
client_app = typer.Typer(help="Client commands: this machine as a device of the Core", no_args_is_help=True)
gateway_app = typer.Typer(help="Web UI of this client: served locally, talks to the Core over the client connection", no_args_is_help=True)
service_app = typer.Typer(help="Background service management", no_args_is_help=True)
client_app.add_typer(gateway_app, name="gateway")
app.add_typer(core_app, name="core")
app.add_typer(client_app, name="client")
app.add_typer(client_app, name="target", hidden=True, help="Deprecated alias of `client`")
app.add_typer(service_app, name="service")
app.add_typer(plugins_app, name="plugins")
app.add_typer(mcp_app, name="mcp")
app.add_typer(skills_app, name="skills")
app.add_typer(automations_app, name="automations")

@app.command()
def version(
    check: Annotated[bool, typer.Option("--check/--no-check", help="Check for a newer release")] = True,
) -> None:
    """Show the installed version and whether an update is available."""
    from mensarium.cli.update import UpdateError, fetch_latest, is_newer, update_source

    roles = [r for r, paths in (("core", CorePaths()), ("client", ClientPaths())) if paths.config.exists()]
    console.print(f"mensarium {__version__}" + (f"  ({', '.join(roles)})" if roles else ""))
    if not check:
        return
    source = update_source()
    try:
        latest = fetch_latest(source, timeout=3)
    except UpdateError:
        return
    if is_newer(latest["version"]):
        console.print(f"Version {latest['version']} is available on {source}. Update: mensarium update")


@app.command()
def update(
    check: Annotated[bool, typer.Option("--check", help="Only check, do not install")] = False,
    force: Annotated[bool, typer.Option("--force", help="Reinstall even if the version is the same")] = False,
    source: Annotated[str | None, typer.Option(help="Update server, e.g. https://mensarium.com")] = None,
) -> None:
    """Update Mensarium: Core from mensarium.com, a client from its Core. Restarts installed services."""
    from mensarium.cli.update import UpdateError, fetch_latest, install, is_newer, update_source

    base = (source or update_source()).rstrip("/")
    try:
        with console.status(f"Checking {base}..."):
            latest = fetch_latest(base)
    except UpdateError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    new = latest["version"]
    if not is_newer(new) and not force:
        ok(f"The latest version {__version__} is installed ({base})")
        return
    if check:
        console.print(f"Version {new} is available (installed {__version__}). Update: mensarium update")
        return
    try:
        with console.status(f"Installing {new}..."):
            restarted = install(base, latest)
    except UpdateError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    ok(f"Mensarium updated: {__version__} -> {new}")
    for role in restarted:
        ok(f"Service {role} restarted")


@app.command()
def setup(
    role: Annotated[str | None, typer.Option(help="core or client")] = None,
    server: Annotated[str | None, typer.Option(help="Core URL (client only)")] = None,
    code: Annotated[str | None, typer.Option(help="Pairing code (client only)")] = None,
    name: Annotated[str | None, typer.Option(help="Client name")] = None,
    service_: Annotated[bool | None, typer.Option("--service/--no-service", help="Install background service")] = None,
) -> None:
    """Interactive installer for the Core or a client."""
    use_select_event_loop()
    from mensarium.cli import wizard

    if role is None:
        role = "client" if (server or code) else None
    if role is None:
        role = wizard.ask(
            questionary.select(
                "What do you want to set up on this machine?",
                choices=[
                    questionary.Choice("Core - main agent with web UI (install once)", "core"),
                    questionary.Choice("Client - a machine the agent can work on", "client"),
                ],
                style=wizard.STYLE,
            )
        )
    if role == "core":
        wizard.setup_core(service_)
    elif role in ("client", "target"):
        wizard.setup_client(server, code, name, service_)
    else:
        fail("role must be core or client")
        raise typer.Exit(2)


@app.command()
def status() -> None:
    """Show what is installed and running on this machine."""
    rows: list[tuple[str, str]] = [("Home", str(mensarium_home())), ("Service backend", service.backend())]
    cpaths = CorePaths()
    if cpaths.config.exists():
        cfg = load_config(cpaths)
        try:
            healthy = httpx.get(f"http://127.0.0.1:{cfg.server.port}/healthz", timeout=2).status_code == 200
        except httpx.HTTPError:
            healthy = False
        rows += [
            ("Core", "running" if healthy else "not responding"),
            ("Core URL", cfg.server.public_url),
            ("LLM", f"{cfg.llm.active_provider} / {cfg.llm.providers[cfg.llm.active_provider].default_model}"),
        ]
    tpaths = ClientPaths()
    if tpaths.config.exists():
        tcfg = load_client_config(tpaths)
        rows += [
            ("Client", f"{tcfg.name} ({tcfg.target_id})"),
            ("Client Core", tcfg.server),
            ("Worker", ("running" if service.is_running("client") else "stopped") if tcfg.worker.enabled else "disabled"),
        ]
        if tcfg.gateway.enabled:
            rows += [
                ("Gateway", "running" if service.is_running("gateway") else "stopped"),
                ("Gateway URL", f"http://{'127.0.0.1' if tcfg.gateway.host in ('127.0.0.1', '0.0.0.0') else tcfg.gateway.host}:{tcfg.gateway.port}"),
            ]
    if len(rows) == 2:
        rows.append(("Status", "nothing configured; run `mensarium setup`"))
    summary("Mensarium status", rows)


@app.command()
def uninstall(
    purge: Annotated[bool, typer.Option(help="Also delete all data, keys and the virtualenv")] = False,
) -> None:
    """Stop services and remove them (optionally purge all data)."""
    use_select_event_loop()
    for role in ("core", "client", "gateway"):
        if service.is_installed(role):  # type: ignore[arg-type]
            service.uninstall(role)  # type: ignore[arg-type]
            ok(f"{role} service removed")
    if purge:
        home = mensarium_home()
        if questionary.confirm(f"Delete {home} with all data and keys?", default=False).ask():
            shutil.rmtree(home, ignore_errors=True)
            link = Path.home() / ".local" / "bin" / "mensarium"
            if link.is_symlink():
                link.unlink()
            ok(f"{home} deleted")


# ---- core -------------------------------------------------------------------


@core_app.command("serve")
def core_serve(
    host: Annotated[str | None, typer.Option(help="Override bind host")] = None,
    port: Annotated[int | None, typer.Option(help="Override port")] = None,
) -> None:
    """Run the Core server in the foreground."""
    import uvicorn

    from mensarium.core.app import create_app

    paths = CorePaths()
    try:
        cfg = load_config(paths)
    except FileNotFoundError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    setup_logging(cfg.log_level)
    uvicorn.run(
        create_app(paths),
        host=host or cfg.server.host,
        port=port or cfg.server.port,
        log_config=None,
        ws_max_size=64 * 1024 * 1024,
    )


@core_app.command("pair-code")
def core_pair_code() -> None:
    """Create a one-time pairing code (valid 10 minutes)."""
    from mensarium.core import pairing
    from mensarium.core.app import PAIRING_TTL_S
    from mensarium.core.db import Database
    from mensarium.core.repo import Repo
    from mensarium.shared.timeutil import iso_in

    paths = CorePaths()
    cfg = load_config(paths)
    code = pairing.generate_code()

    async def run() -> None:
        db = Database(paths.db)
        await db.connect()
        repo = Repo(db)
        await repo.create_pairing(pairing.code_hash(code), iso_in(PAIRING_TTL_S))
        ws = await repo.get_or_create_workspace()
        await repo.audit(ws, "user", "pairing.code_created", {"via": "cli"})
        await db.close()

    asyncio.run(run())
    url = cfg.server.public_url
    summary("Pairing code (valid 10 minutes, one use)", [("Code", code)])
    console.print("Install and pair on the client machine:")
    console.print(f"  curl -fsSL {url}/install.sh | sh -s -- --code {code}", soft_wrap=True, highlight=False)
    console.print("Already installed there:")
    console.print(f"  mensarium client pair --server {url} --code {code} --root <dir>", soft_wrap=True, highlight=False)


@core_app.command("backup")
def core_backup(
    output: Annotated[Path | None, typer.Option("-o", "--output", help="Output .pab file")] = None,
) -> None:
    """Export an encrypted portable bundle (.pab) of the Core."""
    use_select_event_loop()
    from mensarium.cli.backup import BackupError, export_bundle
    from mensarium.shared.timeutil import utcnow

    out = output or Path(f"mensarium-backup-{utcnow():%Y-%m-%d}.pab")
    passphrase = questionary.password("Passphrase to encrypt the bundle:").ask()
    if not passphrase or passphrase != questionary.password("Repeat passphrase:").ask():
        fail("Passphrases are empty or do not match")
        raise typer.Exit(1)
    try:
        info = export_bundle(CorePaths(), out, passphrase)
    except BackupError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    summary(
        "Backup created",
        [(k, str(v)) for k, v in info.items() if k != "encryption"],
        footer=f"Restore on this or another host: mensarium core restore {out}",
    )


@core_app.command("restore")
def core_restore(bundle: Path) -> None:
    """Restore the Core from a .pab bundle (stops the service while restoring)."""
    use_select_event_loop()
    from mensarium.cli.backup import BackupError, import_bundle

    passphrase = questionary.password("Bundle passphrase:").ask() or ""
    was_installed = service.is_installed("core")
    if was_installed:
        service.stop("core")
    try:
        previous = import_bundle(CorePaths(), bundle, passphrase)
    except BackupError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    ok("Core data restored" + (f"; previous data kept in {previous}" if previous else ""))
    cfg = load_config(CorePaths())
    warn(f"Core URL in the bundle: {cfg.server.public_url}. If this host has a different address, run `mensarium setup --role core` -> Reconfigure, then re-pair clients.")
    if was_installed:
        service.install("core")
        ok("Core service restarted")


# ---- client -----------------------------------------------------------------


@client_app.command("pair")
def client_pair(
    server: Annotated[str, typer.Option(help="Core URL, e.g. http://192.168.1.10:8787")],
    code: Annotated[str, typer.Option(help="Pairing code from the Core")],
    root: Annotated[list[str], typer.Option(help="Allowed workspace root (repeatable)")],
    name: Annotated[str | None, typer.Option(help="Client name")] = None,
    full_access: Annotated[bool, typer.Option("--full-access/--no-full-access", help="Allow full-access chats")] = True,
    remote_update: Annotated[
        bool, typer.Option("--remote-update/--no-remote-update", help="Allow updating this agent from the Core web UI")
    ] = True,
    remote_plugins: Annotated[
        bool, typer.Option("--remote-plugins/--no-remote-plugins", help="Allow the Core to run MCP servers here")
    ] = True,
    shell: Annotated[bool, typer.Option("--shell/--no-shell", help="Allow the agent to run bash scripts here (with approval)")] = True,
) -> None:
    """Pair this machine with a Core non-interactively."""
    from mensarium.client.pairing import PairingError, pair

    try:
        cfg = pair(
            ClientPaths(),
            server=server,
            code=code,
            name=name or socket.gethostname().split(".")[0],
            roots=root,
            allow_full_access=full_access,
            allow_remote_update=remote_update,
            allow_remote_plugins=remote_plugins,
            allow_shell=shell,
        )
    except PairingError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    ok(f"Paired as {cfg.name} ({cfg.target_id}); core fingerprint {cfg.core_fingerprint}")
    if service.is_installed("client"):
        service.restart("client")
        ok("Client service restarted")
    else:
        console.print("Start the agent with `mensarium client run` or `mensarium service install client`.")


@client_app.command("plugins")
def client_plugins_cmd() -> None:
    """Show the MCP servers the Core runs on this device."""
    target_plugins()


@client_app.command("permissions")
def client_permissions() -> None:
    """Ask the OS again for the desktop permissions the agent needs (screen recording, accessibility)."""
    import json

    from mensarium.client import desktop

    paths = ClientPaths()
    if not paths.config.exists():
        fail("this machine is not paired as a client")
        raise typer.Exit(1)
    console.print("Desktop tools on this device: " + (", ".join(desktop.available_tools()) or "none"))
    if sys.platform == "darwin":
        try:
            paths.permissions.write_text(json.dumps({"reask": True}))
        except OSError:
            pass
        if service.is_running("client"):
            service.restart("client")
            ok("The agent restarts and macOS asks to allow Screen Recording and Accessibility for Mensarium. Allow both in the dialogs or in System Settings -> Privacy & Security.")
        else:
            desktop.request_permissions()
            ok("macOS asked for Screen Recording and Accessibility; start the agent afterwards.")
        if not shutil.which("cliclick"):
            warn("Mouse moves need cliclick: brew install cliclick (clicks work without it).")
        return
    missing = [name for name in ("xdotool", "wmctrl", "grim", "scrot") if not shutil.which(name)]
    perms = desktop.permissions()
    ok(f"screen capture: {'ready' if perms.get('screen') else 'no tool'}, input control: {'ready' if perms.get('input') else 'no tool'}")
    if missing:
        warn("Missing tools: " + ", ".join(missing) + " (apt install xdotool wmctrl scrot, or grim on Wayland)")


@client_app.command("run")
def client_run() -> None:
    """Run the client agent in the foreground."""
    from mensarium.client.agent import ClientAgent
    from mensarium.shared.crypto import load_or_create_private_key

    setup_logging("INFO")
    paths = ClientPaths()
    try:
        cfg = load_client_config(paths)
    except FileNotFoundError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    if not cfg.worker.enabled:
        fail("the worker is disabled on this client; enable it with `mensarium client setup`")
        raise typer.Exit(1)
    agent = ClientAgent(cfg, paths, load_or_create_private_key(paths.key))
    try:
        asyncio.run(agent.run_forever())
    except KeyboardInterrupt:
        pass


# ---- client gateway ---------------------------------------------------------


def _gateway_config() -> tuple[ClientPaths, ClientConfig]:
    paths = ClientPaths()
    try:
        cfg = load_client_config(paths)
    except FileNotFoundError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    return paths, cfg


def _gateway_url(cfg: ClientConfig) -> str:
    if cfg.gateway.host in ("127.0.0.1", "0.0.0.0", "localhost"):
        host = f"127.0.0.1:{cfg.gateway.port}"
    else:
        host = f"{cfg.gateway.host}:{cfg.gateway.port}"
    return f"http://{host}"


@gateway_app.command("run")
def gateway_run() -> None:
    """Run the gateway in the foreground: the web UI on this machine."""
    from mensarium.client.gateway.server import run_gateway

    setup_logging("INFO")
    paths, cfg = _gateway_config()
    if not cfg.gateway.enabled:
        fail("the gateway is disabled on this client; enable it with `mensarium client setup`")
        raise typer.Exit(1)
    try:
        asyncio.run(run_gateway(cfg, paths))
    except KeyboardInterrupt:
        pass


@gateway_app.command("token")
def gateway_token(
    rotate: Annotated[bool, typer.Option("--rotate", help="Replace the token; open browser sessions are logged out")] = False,
) -> None:
    """Print the token for logging into the web UI of this gateway."""
    from mensarium.client.gateway import auth

    paths, _ = _gateway_config()
    console.print(auth.rotate_token(paths) if rotate else auth.load_or_create_token(paths))


@gateway_app.command("open")
def gateway_open() -> None:
    """Open the web UI in the browser with a one-time login link."""
    import webbrowser

    from mensarium.client.gateway import auth

    paths, cfg = _gateway_config()
    url = f"{_gateway_url(cfg)}/login?link={auth.write_link(paths)}"
    console.print(url, soft_wrap=True, highlight=False)
    webbrowser.open(url)


@gateway_app.command("status")
def gateway_status() -> None:
    """Show whether the gateway runs and is connected to the Core."""
    _, cfg = _gateway_config()
    rows: list[tuple[str, str]] = [("Enabled", "yes" if cfg.gateway.enabled else "no"), ("URL", _gateway_url(cfg))]
    try:
        state = httpx.get(f"{_gateway_url(cfg)}/v1/gateway", timeout=2).json()
        rows += [("Gateway", "running"), ("Core", "connected" if state.get("online") else "offline")]
        if state.get("rejected"):
            rows.append(("Rejected", f"{state['rejected']}; pair this client again"))
    except (httpx.HTTPError, ValueError):
        rows.append(("Gateway", "not running"))
    if service.is_installed("gateway"):
        rows.append(("Service", "running" if service.is_running("gateway") else "stopped"))
    summary("Gateway", rows)


# ---- service ----------------------------------------------------------------


@service_app.command("install")
def service_install(role: service.Unit) -> None:
    """Install and start the background service."""
    ok(f"{role}: {service.install(role)}")


@service_app.command("uninstall")
def service_uninstall(role: service.Unit) -> None:
    """Stop and remove the background service."""
    service.uninstall(role)
    ok(f"{role} service removed")


@service_app.command("stop")
def service_stop(role: service.Unit) -> None:
    """Stop the background service; it starts again on login or `service restart`."""
    service.stop(role)
    ok(f"{role} service stopped")


@service_app.command("restart")
def service_restart(role: service.Unit) -> None:
    """Restart the background service."""
    service.restart(role)
    ok(f"{role} service restarted")


@service_app.command("logs")
def service_logs(role: service.Unit, lines: int = 100) -> None:
    """Follow the service log."""
    subprocess.run(["tail", "-n", str(lines), "-F", str(service.log_file(role))])
