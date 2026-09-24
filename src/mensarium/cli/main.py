import asyncio
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Annotated, Literal

import httpx
import questionary
import typer

from mensarium import __version__
from mensarium.cli import service
from mensarium.cli.ui import console, fail, ok, summary, use_select_event_loop, warn
from mensarium.core.config import CorePaths, load_config, read_secret
from mensarium.shared.logging import setup_logging
from mensarium.shared.paths import mensarium_home
from mensarium.target.config import TargetPaths, load_target_config

app = typer.Typer(help="Mensarium: portable agent harness (Core + Target Agent)", no_args_is_help=True)
core_app = typer.Typer(help="Main agent (Core) commands", no_args_is_help=True)
target_app = typer.Typer(help="Target Agent commands", no_args_is_help=True)
service_app = typer.Typer(help="Background service management", no_args_is_help=True)
app.add_typer(core_app, name="core")
app.add_typer(target_app, name="target")
app.add_typer(service_app, name="service")

Role = Literal["core", "target"]


@app.command()
def version() -> None:
    """Print the version."""
    console.print(__version__)


@app.command()
def setup(
    role: Annotated[str | None, typer.Option(help="core or target")] = None,
    server: Annotated[str | None, typer.Option(help="Core URL (target only)")] = None,
    code: Annotated[str | None, typer.Option(help="Pairing code (target only)")] = None,
    name: Annotated[str | None, typer.Option(help="Target name")] = None,
    service_: Annotated[bool | None, typer.Option("--service/--no-service", help="Install background service")] = None,
) -> None:
    """Interactive installer for the Core or a Target Agent."""
    use_select_event_loop()
    from mensarium.cli import wizard

    if role is None:
        role = "target" if (server or code) else None
    if role is None:
        role = wizard.ask(
            questionary.select(
                "What do you want to set up on this machine?",
                choices=[
                    questionary.Choice("Core - main agent with web UI (install once)", "core"),
                    questionary.Choice("Target - a machine the agent can work on", "target"),
                ],
                style=wizard.STYLE,
            )
        )
    if role == "core":
        wizard.setup_core(service_)
    elif role == "target":
        wizard.setup_target(server, code, name, service_)
    else:
        fail("role must be core or target")
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
    tpaths = TargetPaths()
    if tpaths.config.exists():
        tcfg = load_target_config(tpaths)
        rows += [
            ("Target", f"{tcfg.name} ({tcfg.target_id})"),
            ("Target service", "running" if service.is_running("target") else "stopped"),
            ("Target Core", tcfg.server),
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
    for role in ("core", "target"):
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


@core_app.command("token")
def core_token() -> None:
    """Print the admin token for the web UI."""
    token = read_secret(CorePaths(), "secret://admin-token")
    if not token:
        fail("Core is not configured")
        raise typer.Exit(1)
    console.print(token)


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
    console.print("Install and pair on the target machine:")
    console.print(f"  curl -fsSL {url}/install.sh | sh -s -- --code {code}", soft_wrap=True, highlight=False)
    console.print("Already installed there:")
    console.print(f"  mensarium target pair --server {url} --code {code} --root <dir>", soft_wrap=True, highlight=False)


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
    summary("Backup created", [(k, str(v)) for k, v in info.items() if k != "encryption"])


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
    warn(f"Core URL in the bundle: {cfg.server.public_url}. If this host has a different address, run `mensarium setup --role core` -> Reconfigure, then re-pair targets.")
    if was_installed:
        service.install("core")
        ok("Core service restarted")


# ---- target -----------------------------------------------------------------


@target_app.command("pair")
def target_pair(
    server: Annotated[str, typer.Option(help="Core URL, e.g. http://192.168.1.10:8787")],
    code: Annotated[str, typer.Option(help="Pairing code from the Core")],
    root: Annotated[list[str], typer.Option(help="Allowed workspace root (repeatable)")],
    name: Annotated[str | None, typer.Option(help="Target name")] = None,
) -> None:
    """Pair this machine with a Core non-interactively."""
    from mensarium.target.pairing import PairingError, pair

    try:
        cfg = pair(TargetPaths(), server=server, code=code, name=name or socket.gethostname().split(".")[0], roots=root)
    except PairingError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    ok(f"Paired as {cfg.name} ({cfg.target_id}); core fingerprint {cfg.core_fingerprint}")
    if service.is_installed("target"):
        service.restart("target")
        ok("Target service restarted")
    else:
        console.print("Start the agent with `mensarium target run` or `mensarium service install target`.")


@target_app.command("run")
def target_run() -> None:
    """Run the Target Agent in the foreground."""
    from mensarium.shared.crypto import load_or_create_private_key
    from mensarium.target.agent import TargetAgent

    setup_logging("INFO")
    paths = TargetPaths()
    try:
        cfg = load_target_config(paths)
    except FileNotFoundError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    agent = TargetAgent(cfg, paths, load_or_create_private_key(paths.key))
    try:
        asyncio.run(agent.run_forever())
    except KeyboardInterrupt:
        pass


# ---- service ----------------------------------------------------------------


@service_app.command("install")
def service_install(role: Role) -> None:
    """Install and start the background service."""
    ok(f"{role}: {service.install(role)}")


@service_app.command("uninstall")
def service_uninstall(role: Role) -> None:
    """Stop and remove the background service."""
    service.uninstall(role)
    ok(f"{role} service removed")


@service_app.command("restart")
def service_restart(role: Role) -> None:
    """Restart the background service."""
    service.restart(role)
    ok(f"{role} service restarted")


@service_app.command("logs")
def service_logs(role: Role, lines: int = 100) -> None:
    """Follow the service log."""
    subprocess.run(["tail", "-n", str(lines), "-F", str(service.log_file(role))])
