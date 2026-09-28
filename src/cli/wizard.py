import asyncio
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx
import questionary
import typer

from mensarium.cli import service
from mensarium.cli.backup import (
    BackupError,
    Item,
    backup_items,
    can_write,
    export_bundle,
    human,
    import_bundle,
    planned_roots,
    read_manifest,
)
from mensarium.cli.ui import banner, console, fail, ok, step, summary, warn
from mensarium.client.config import (
    DEFAULT_COMMAND_ALLOWLIST,
    ClientConfig,
    ClientPaths,
    load_client_config,
    save_client_config,
)
from mensarium.client.pairing import PairingError, pair
from mensarium.core.config import (
    CoreConfig,
    CorePaths,
    DeviceConfig,
    LLMConfig,
    ProviderConfig,
    ServerConfig,
    load_config,
    read_secret,
    save_config,
    write_secret,
)
from mensarium.core.device import device_name
from mensarium.llm_providers.factory import PROVIDER_KINDS, is_cli
from mensarium.llm_providers.local_cli import detect_local_clis
from mensarium.shared.crypto import fingerprint, load_or_create_private_key, public_key_b64

STYLE = questionary.Style(
    [("qmark", "fg:#22d3ee bold"), ("pointer", "fg:#22d3ee bold"), ("highlighted", "fg:#22d3ee bold"),
     ("selected", "fg:#4ade80"), ("answer", "fg:#4ade80 bold")]
)  # fmt: skip
CODE_RE = re.compile(r"^[A-Za-z]+-[A-Za-z]+-\d{4}$")


def ask(question: questionary.Question) -> Any:
    answer = question.ask()
    if answer is None:
        raise typer.Abort()
    return answer


def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))
            return str(s.getsockname()[0])
    except OSError:
        return "127.0.0.1"


def fetch_models(base_url: str, api_key: str | None) -> list[str]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    resp = httpx.get(f"{base_url.rstrip('/')}/models", headers=headers, timeout=15)
    resp.raise_for_status()
    return sorted(m["id"] for m in resp.json().get("data", []))


def wait_healthy(url: str, timeout_s: float = 25) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url.rstrip('/')}/healthz", timeout=2).status_code == 200:
                return True
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    return False


# ---- core -------------------------------------------------------------------


def setup_core(start_service: bool | None = None) -> None:
    paths = CorePaths()
    banner("Core setup: the main agent, the web UI and this machine as the agent's first device")
    existing: CoreConfig | None = None
    if paths.config.exists():
        existing = load_config(paths)
        action = ask(
            questionary.select(
                "Core is already configured on this machine.",
                choices=["Keep the configuration and (re)start", "Reconfigure"],
                style=STYLE,
            )
        )
        if action.startswith("Keep"):
            _finish_core(paths, existing, start_service)
            return

    total = 4
    step(1, total, "Network")
    port = int(
        ask(
            questionary.text(
                "Port for the API (clients connect here):",
                default=str(existing.server.port if existing else 8787),
                validate=lambda v: v.isdigit() and 0 < int(v) < 65536 or "Enter a port number",
                style=STYLE,
            )
        )
    )
    bind = ask(
        questionary.select(
            "Who should be able to reach the Core?",
            choices=[
                questionary.Choice("Devices in my network (clients on other machines)", "0.0.0.0"),
                questionary.Choice("Only this machine (localhost)", "127.0.0.1"),
            ],
            style=STYLE,
        )
    )
    host_guess = lan_ip() if bind == "0.0.0.0" else "127.0.0.1"
    public_url = ask(
        questionary.text(
            "URL clients will use to reach the Core:",
            default=f"http://{host_guess}:{port}",
            validate=lambda v: v.startswith(("http://", "https://")) or "Must start with http:// or https://",
            style=STYLE,
        )
    ).rstrip("/")

    step(2, total, "LLM provider")
    with console.status("Looking for Claude Code and Codex on this machine..."):
        detected = {cli.kind: cli for cli in detect_local_clis()}
    local_choices = [
        questionary.Choice(
            f"{cli.title} on this machine (v{cli.version or '?'}, {'logged in' if cli.logged_in else 'not logged in'}, no API key needed)",
            cli.kind,
        )
        for cli in detected.values()
    ]
    provider = ask(
        questionary.select(
            "Where does the model run?",
            choices=[
                *local_choices,
                questionary.Choice("Ollama Cloud (ollama.com, API key)", "ollama_cloud"),
                questionary.Choice("Local Ollama (this machine or LAN)", "ollama_local"),
                questionary.Choice("llama.cpp server", "llama_cpp"),
                questionary.Choice("LM Studio", "lmstudio"),
                questionary.Choice("OpenAI (API key)", "openai"),
                questionary.Choice("OpenRouter (API key)", "openrouter"),
                questionary.Choice("Another OpenAI-compatible server", "openai_compatible"),
            ],
            style=STYLE,
        )
    )
    kind = PROVIDER_KINDS[provider]
    api_key: str | None = None
    api_key_ref: str | None = None
    models: list[str] = []
    if is_cli(provider):
        cli = detected.get(provider)
        base_url = cli.path if cli else ask(questionary.text(f"Path to the {kind['title']} command:", default=str(kind["base_url"]), style=STYLE))
        if cli and cli.logged_in is False:
            warn(f"{cli.title} is not logged in; run `{cli.path}` here and log in, otherwise the agent cannot think.")
        models = cli.models if cli else []
        kind = {**kind, "default_model": (cli.default_model if cli else kind["default_model"])}
    else:
        base_url = ask(questionary.text("Provider base URL:", default=str(kind["base_url"]), style=STYLE)).rstrip("/")
        secret_name = "ollama-api-key" if provider == "ollama_cloud" else f"provider-{provider}-key"
        current = read_secret(paths, f"secret://{secret_name}") if existing else None
        hint = " (leave empty to keep the current one)" if current else "" if kind["needs_key"] else " (leave empty if the server needs none)"
        entered = ask(questionary.password(f"{kind['title']} API key{hint}:", style=STYLE)).strip()
        api_key = entered or current
        if kind["needs_key"] and not api_key:
            fail(f"An API key is required for {kind['title']} ({kind['key_url']}).")
            raise typer.Exit(1)
        if api_key:
            api_key_ref = f"secret://{secret_name}"
        with console.status("Checking the provider and loading models..."):
            try:
                models = fetch_models(base_url, api_key)
            except httpx.HTTPError as e:
                warn(f"Could not load models: {e}")
    if models:
        ok(f"Provider reachable, {len(models)} models available")
        default_model = str(kind["default_model"]) if kind["default_model"] in models else models[0]
        model = ask(
            questionary.autocomplete(
                "Default model (type to filter, Tab to complete):",
                choices=models,
                default=default_model,
                validate=lambda v: bool(v.strip()) or "Enter a model name",
                style=STYLE,
            )
        )
    else:
        model = ask(questionary.text("Default model:", default=str(kind["default_model"]), style=STYLE))

    step(3, total, "This machine as a device")
    device = existing.device if existing else DeviceConfig()
    device.name = ask(questionary.text("Name for this machine:", default=device.name or socket.gethostname().split(".")[0], style=STYLE))
    access = ask_device_access(device.roots, device.command_allowlist, device.allow_full_access, device.allow_shell, device.allow_remote_plugins)
    device = DeviceConfig(name=device.name, **access)

    paths.ensure()
    if api_key and api_key_ref:
        write_secret(paths, api_key_ref.removeprefix("secret://"), api_key)
    key = load_or_create_private_key(paths.signing_key)
    ok(f"Core signing key fingerprint: {fingerprint(public_key_b64(key))}")

    cfg = CoreConfig(
        server=ServerConfig(host=bind, port=port, public_url=public_url),
        device=device,
        llm=LLMConfig(
            active_provider=provider,
            providers={
                provider: ProviderConfig(
                    kind=provider,
                    base_url=base_url,
                    default_model=model,
                    api_key_ref=api_key_ref,
                    timeout_s=180 if (is_cli(provider) or not kind["needs_key"]) else 90,
                    max_retries=1 if is_cli(provider) else 2 if kind["needs_key"] else 0,
                )
            },
        ),
    )
    save_config(paths, cfg)
    ok(f"Configuration saved to {paths.config}")
    step(4, total, "Service")
    _finish_core(paths, cfg, start_service)


def _finish_core(paths: CorePaths, cfg: CoreConfig, start_service: bool | None) -> None:
    from mensarium.client.gateway import auth

    if start_service is None:
        start_service = ask(
            questionary.confirm(
                "Run the Core as a background service (starts on login/boot)?", default=True, style=STYLE
            )
        )
    local_url = f"http://127.0.0.1:{cfg.server.port}"
    if start_service:
        with console.status("Starting the Core service..."):
            how = service.install("core")
            healthy = wait_healthy(local_url)
        if healthy:
            ok(f"Core is running ({how})")
        else:
            fail(f"Core did not become healthy; see logs: {service.log_file('core')}")
            raise typer.Exit(1)
    if cfg.device.enabled:
        _desktop_setup()
    summary(
        "Mensarium Core is ready",
        [
            ("Core URL", cfg.server.public_url),
            ("Provider", f"{cfg.llm.active_provider} / {cfg.llm.providers[cfg.llm.active_provider].default_model}"),
            ("Device", f"{device_name(cfg)}: {', '.join(cfg.device.roots) or '~'}" if cfg.device.enabled else "disabled"),
            ("Data", str(paths.root)),
            ("Logs", str(service.log_file("core"))),
        ],
        footer=(
            f"Open the web UI: {cfg.server.public_url}/login?link={auth.write_link(paths.device)} (one-time link)\n"
            "Later: mensarium core open, token: mensarium core token\n"
            "Other machines: `mensarium core pair-code` here, `mensarium client` there."
            + ("" if start_service else "\nStart manually: mensarium core serve")
        ),
    )


# ---- backup and move ----------------------------------------------------------


def _item_label(item: Item) -> str:
    extra = f", {human(item.skipped)} of node_modules/.venv/builds skipped" if item.skipped else ""
    return f"{item.title} ({human(item.size)}{extra})"


def _stop_for_move(moved_to: str, local_url: str, was_installed: bool) -> None:
    """Tell the clients the new address, then stop this Core for good so nothing changes after the snapshot."""
    from mensarium.cli.plugins import ApiError, _api

    if wait_healthy(local_url, timeout_s=2):
        try:
            answer = _api("POST", "/v1/core/move", {"url": moved_to})
        except ApiError as e:
            fail(f"Could not tell the clients about the move: {e}")
            raise typer.Exit(1) from e
        if answer["told"]:
            ok("New address sent to: " + ", ".join(answer["told"]))
        if answer["missed"]:
            warn(f"Offline now, switch them later with `mensarium client move {moved_to}` there: " + ", ".join(answer["missed"]))
    else:
        warn(f"The Core is not running, so clients were not told; run `mensarium client move {moved_to}` on each of them.")
    if was_installed:
        with console.status("Stopping the Core service..."):
            service.uninstall("core")
    with console.status("Waiting for the Core to stop (press Ctrl+C in its terminal if it runs in the foreground)..."):
        while wait_healthy(local_url, timeout_s=1):
            time.sleep(1)
    ok("The Core on this machine is stopped")


def backup_core(output: Path | None) -> None:
    from mensarium.shared.timeutil import utcnow

    paths = CorePaths()
    if not paths.config.exists():
        fail("The Core is not configured on this machine")
        raise typer.Exit(1)
    cfg = load_config(paths)
    moved_to = None
    if ask(questionary.confirm("Is this a move to another server? Clients get the new address and this Core stops.", default=False, style=STYLE)):
        moved_to = ask(
            questionary.text(
                "Core URL on the new server (clients will use it):",
                validate=lambda v: v.startswith(("http://", "https://")) or "Must start with http:// or https://",
                style=STYLE,
            )
        ).strip().rstrip("/")
    with console.status("Measuring what can go into the bundle..."):
        core, items = backup_items(paths, cfg)
    console.print(f"Always in the bundle: {core.title} ({human(core.size)})")
    chosen = (
        ask(
            questionary.checkbox(
                "Also take (space toggles, enter confirms):",
                choices=[questionary.Choice(_item_label(i), i, checked=i.default) for i in items],
                style=STYLE,
            )
        )
        if items
        else []
    )
    passphrase = ask(questionary.password("Passphrase to encrypt the bundle:", style=STYLE))
    if not passphrase or passphrase != ask(questionary.password("Repeat passphrase:", style=STYLE)):
        fail("Passphrases are empty or do not match")
        raise typer.Exit(1)
    out = output or Path(f"mensarium-backup-{utcnow():%Y-%m-%d}.pab")
    was_installed = service.is_installed("core")
    if moved_to:
        _stop_for_move(moved_to, f"http://127.0.0.1:{cfg.server.port}", was_installed)
    try:
        with console.status(f"Writing {out}..."):
            info = export_bundle(paths, out, passphrase, chosen, moved_to)
    except (BackupError, OSError) as e:
        fail(str(e))
        if moved_to and was_installed:
            service.install("core")
            warn("The Core on this machine is started again; clients stay with it until the new one is up.")
        raise typer.Exit(1) from e
    for problem in info["problems"][:20]:
        warn(f"Not copied: {problem}")
    footer = f"Restore on this or another host: mensarium core restore {out}"
    if moved_to:
        footer = (
            f"Copy {out} to the new server, install Mensarium there:\n  curl -fsSL https://mensarium.com/install.sh | sh\n"
            f"and run:\n  mensarium core restore {out.name}\n"
            f"Clients that got the address switch to {moved_to} by themselves once the new Core is up."
        )
    summary(
        "Backup created",
        [("File", info["file"]), ("Size", human(info["size"])), ("SHA-256", info["sha256"]), ("Contents", ", ".join(["core", *info["items"]]))],
        footer=footer,
    )


def restore_core(bundle: Path) -> None:
    import tarfile

    paths = CorePaths()
    passphrase = ask(questionary.password("Bundle passphrase:", style=STYLE))
    try:
        with console.status("Reading the bundle..."):
            manifest = read_manifest(bundle, passphrase)
    except (BackupError, OSError, tarfile.TarError) as e:
        fail(str(e))
        raise typer.Exit(1) from e
    roots = planned_roots(manifest)
    olds = {int(r["id"]): r["path"] for r in manifest.get("roots", [])}
    for n, dest in roots.items():
        if not can_write(dest):
            answer = ask(questionary.text(f"No permission to write {dest}. Where to put {olds[n]}?", default=str(Path.home() / dest.name), style=STYLE))
            roots[n] = Path(answer).expanduser().resolve()
    if roots:
        console.print("Folders of the Core's device go to:")
        for n, dest in roots.items():
            busy = dest.exists() and any(dest.iterdir())
            console.print(f"  {olds[n]} -> {dest}" + ("  (exists: files with the same names are replaced)" if busy else ""))
        if not ask(questionary.confirm("Restore them there?", default=True, style=STYLE)):
            raise typer.Abort()
    was_installed = service.is_installed("core")
    if was_installed:
        service.stop("core")
    try:
        with console.status("Restoring..."):
            restored = import_bundle(paths, bundle, passphrase, roots)
    except (BackupError, OSError, tarfile.TarError) as e:
        fail(str(e))
        raise typer.Exit(1) from e
    ok("Core data restored" + (f"; previous data kept in {restored.previous}" if restored.previous else ""))
    for warning in restored.warnings:
        warn(warning)
    cfg = load_config(paths)
    if not manifest.get("moved_to"):
        url = ask(
            questionary.text(
                "URL clients will use to reach the Core:",
                default=cfg.server.public_url,
                validate=lambda v: v.startswith(("http://", "https://")) or "Must start with http:// or https://",
                style=STYLE,
            )
        ).rstrip("/")
        if url != cfg.server.public_url:
            cfg.server.public_url = url
            save_config(paths, cfg)
            warn(f"The address changed: on each client run `mensarium client move {url}`.")
    _finish_core(paths, cfg, True if was_installed else None)
    _check_provider(cfg)


def _check_provider(cfg: CoreConfig) -> None:
    from mensarium.cli.plugins import ApiError, _api

    if not wait_healthy(f"http://127.0.0.1:{cfg.server.port}", timeout_s=2):
        return
    try:
        health = _api("GET", "/v1/system")["provider"]["health"]
    except (ApiError, KeyError, TypeError):
        return
    if not health.get("ok"):
        warn(f"The model provider does not answer on this machine: {health.get('detail') or 'unknown error'}. Fix it with `mensarium core setup` (a local Claude Code or Codex needs a login here).")


def move_client(url: str | None) -> None:
    """Point this client at the Core's new address; the Core there must hold the same key."""
    from mensarium.client import moving

    paths = ClientPaths()
    cfg = load_client_config(paths)
    url = (
        url
        or ask(
            questionary.text(
                "New Core URL:",
                default=cfg.moved_to or "",
                validate=lambda v: v.startswith(("http://", "https://")) or "e.g. http://192.168.1.10:8787",
                style=STYLE,
            )
        )
    ).strip().rstrip("/")
    try:
        with console.status(f"Checking the Core at {url}..."):
            asyncio.run(moving.switch(paths, cfg, url))
    except moving.MoveError as e:
        fail(str(e))
        raise typer.Exit(1) from e
    ok(f"This client now works with the Core at {url}")
    for unit, enabled in (("client", cfg.worker.enabled), ("gateway", cfg.gateway.enabled)):
        if enabled and service.is_installed(unit):  # type: ignore[arg-type]
            service.restart(unit)  # type: ignore[arg-type]
            ok(f"{unit} restarted")


# ---- target -----------------------------------------------------------------


def _root_candidates() -> list[str]:
    home = Path.home()
    names = ["Projects", "projects", "Code", "code", "src", "dev", "work", "workspace", "repos", "Developer"]
    found = [str(home / n) for n in names if (home / n).is_dir()]
    cwd = Path.cwd()
    if cwd != home and cwd.is_dir() and str(cwd) not in found and not str(cwd).startswith("/tmp"):
        found.append(str(cwd))
    return found


def setup_client(server: str | None, code: str | None, name: str | None, start_service: bool | None) -> None:
    paths = ClientPaths()
    if CorePaths().config.exists():
        fail("This machine runs the Core and is already its device; the web UI is served by the Core (mensarium core open).")
        raise typer.Exit(1)
    banner("Client setup: this machine becomes a device of the Core")
    if paths.config.exists():
        current = load_client_config(paths)
        action = ask(
            questionary.select(
                f"This machine is already paired as '{current.name}' with {current.server}.",
                choices=["Keep the pairing and (re)start the agent", "The Core moved to a new address", "Pair again (new code)"],
                style=STYLE,
            )
        )
        if action.startswith("The Core moved"):
            move_client(None)
            return
        if action.startswith("Keep"):
            configure_client_roles(paths, current)
            finish_client(paths, start_service)
            return

    total = 4
    step(1, total, "Connect to the Core")
    while True:
        server = (
            server
            or ask(
                questionary.text(
                    "Core URL:",
                    validate=lambda v: v.startswith(("http://", "https://")) or "e.g. http://192.168.1.10:8787",
                    style=STYLE,
                )
            )
        ).rstrip("/")
        with console.status(f"Contacting {server}..."):
            reachable = wait_healthy(server, timeout_s=5)
        if reachable:
            ok(f"Core reachable at {server}")
            break
        fail(f"Core is not reachable at {server}")
        server = None

    step(2, total, "Workspace access")
    access = ask_device_access([], list(DEFAULT_COMMAND_ALLOWLIST), True, True, True)
    remote_update = ask(
        questionary.confirm(
            "Allow the Core to update this agent from its web UI (downloads the release from the Core and restarts the agent)?",
            default=True,
            style=STYLE,
        )
    )

    step(3, total, "Pairing")
    name = name or ask(questionary.text("Name for this machine:", default=socket.gethostname().split(".")[0], style=STYLE))
    while True:
        code = code or ask(
            questionary.text(
                "Pairing code from the Core (Devices -> Pair new device):",
                validate=lambda v: bool(CODE_RE.match(v.strip())) or "Format: WORD-WORD-1234",
                style=STYLE,
            )
        )
        try:
            with console.status("Pairing..."):
                cfg = pair(
                    paths,
                    server=server,
                    code=code.strip(),
                    name=name,
                    roots=access["roots"],
                    command_allowlist=access["command_allowlist"],
                    allow_full_access=access["allow_full_access"],
                    allow_remote_update=remote_update,
                    allow_remote_plugins=access["allow_remote_plugins"],
                    allow_shell=access["allow_shell"],
                )
            break
        except PairingError as e:
            fail(str(e))
            code = None
    ok(f"Paired as {cfg.target_id}")
    ok(f"Core key fingerprint: {cfg.core_fingerprint} (compare with Settings in the web UI)")

    step(4, total, "Service")
    configure_client_roles(paths, cfg)
    finish_client(paths, start_service)


def ask_device_access(
    roots: list[str], allowlist: list[str], full_access: bool, allow_shell: bool, remote_plugins: bool
) -> dict[str, Any]:
    """What the agent may touch on this machine; the same questions for a client and for the Core's own device."""
    choices = [questionary.Choice(p, p, checked=(p in roots) if roots else i == 0) for i, p in enumerate(dict.fromkeys([*roots, *_root_candidates()]))]
    roots = []
    if choices:
        roots = ask(
            questionary.checkbox(
                "Folders the agent may read and work in (Space to toggle, Enter to confirm):",
                choices=choices,
                style=STYLE,
            )
        )
    extra = ask(
        questionary.path(
            "Add another folder (empty to skip):", only_directories=True, default="", style=STYLE
        )
    ).strip()
    if extra:
        roots.append(str(Path(extra).expanduser().resolve()))
    while not roots:
        warn("At least one folder is required.")
        roots = [str(Path(ask(questionary.path("Folder:", only_directories=True, style=STYLE))).expanduser().resolve())]

    mode = ask(
        questionary.select(
            "Which programs may shell.exec run (every run still needs your approval)?",
            choices=[
                questionary.Choice("Common developer tools (git, python, pytest, npm, make, ...)", "default"),
                questionary.Choice("Any program on PATH", "any"),
                questionary.Choice("Custom list", "custom"),
            ],
            default="any" if allowlist == ["*"] else "custom" if allowlist != DEFAULT_COMMAND_ALLOWLIST else "default",
            style=STYLE,
        )
    )
    if mode == "any":
        allowlist = ["*"]
    elif mode == "custom":
        raw = ask(questionary.text("Programs, comma separated:", default=", ".join(allowlist), style=STYLE))
        allowlist = [p.strip() for p in raw.split(",") if p.strip()]
    else:
        allowlist = list(DEFAULT_COMMAND_ALLOWLIST)

    full_access = ask(
        questionary.confirm(
            "Allow full-access mode on this machine (all files and programs, including system commands, without asking, within OS permissions)?",
            default=full_access,
            style=STYLE,
        )
    )
    remote_plugins = ask(
        questionary.confirm(
            "Allow the Core to run MCP servers from plugins on this machine (programs must be in the list above)?",
            default=remote_plugins,
            style=STYLE,
        )
    )
    allow_shell = ask(
        questionary.confirm(
            "Allow the agent to run bash scripts on this machine (each script is approved by you in the chat)?",
            default=allow_shell,
            style=STYLE,
        )
    )
    return {
        "roots": roots,
        "command_allowlist": allowlist,
        "allow_full_access": full_access,
        "allow_shell": allow_shell,
        "allow_remote_plugins": remote_plugins,
    }


def configure_client_roles(paths: ClientPaths, cfg: ClientConfig) -> ClientConfig:
    """What this client does: run the agent's tools here (worker) and/or serve the web UI here (gateway)."""
    cfg.worker.enabled = ask(
        questionary.confirm("Let the agent work on this machine (run tools here)?", default=cfg.worker.enabled, style=STYLE)
    )
    cfg.gateway.enabled = ask(questionary.confirm("Open the web UI on this machine (gateway)?", default=True, style=STYLE))
    if cfg.gateway.enabled:
        cfg.gateway.port = int(
            ask(
                questionary.text(
                    "Gateway port:",
                    default=str(cfg.gateway.port),
                    validate=lambda v: v.isdigit() and 0 < int(v) < 65536 or "Enter a port number",
                    style=STYLE,
                )
            )
        )
        cfg.gateway.host = ask(
            questionary.select(
                "Who may open the web UI?",
                choices=[
                    questionary.Choice("Only this machine (localhost)", "127.0.0.1"),
                    questionary.Choice("Other machines too (they log in with the gateway token)", "0.0.0.0"),
                ],
                default=cfg.gateway.host if cfg.gateway.host in ("127.0.0.1", "0.0.0.0") else "127.0.0.1",
                style=STYLE,
            )
        )
        if cfg.gateway.host == "0.0.0.0":
            hosts = ask(
                questionary.text(
                    "Addresses the browser will use (host:port, comma separated):",
                    default=", ".join(cfg.gateway.allowed_hosts) or f"{lan_ip()}:{cfg.gateway.port}",
                    style=STYLE,
                )
            )
            cfg.gateway.allowed_hosts = [h.strip() for h in hosts.split(",") if h.strip()]
    save_client_config(paths, cfg)
    return cfg


def _desktop_setup() -> None:
    """Screen and input control need OS permissions and, on macOS, cliclick for mouse moves."""
    if sys.platform == "darwin":
        console.print(
            "macOS now asks to allow [bold]Screen Recording[/bold] and [bold]Accessibility[/bold] for Mensarium: allow both so the agent "
            "can see the screen and use the mouse and keyboard. Later: [bold]mensarium client permissions[/bold]."
        )
        if not shutil.which("cliclick") and shutil.which("brew") and ask(
            questionary.confirm("Install cliclick with Homebrew so the agent can move the mouse?", default=True, style=STYLE)
        ):
            with console.status("brew install cliclick..."):
                result = subprocess.run(["brew", "install", "cliclick"], capture_output=True, text=True)
            if result.returncode == 0:
                ok("cliclick installed")
            else:
                warn(f"brew install cliclick failed: {result.stderr.strip()[-300:]}")
        return
    missing = [name for name in ("xdotool", "wmctrl", "scrot", "grim") if not shutil.which(name)]
    if missing:
        console.print("For screen and input control install: " + ", ".join(missing) + " (apt install xdotool wmctrl scrot; grim on Wayland).")


def _gateway_url(cfg: ClientConfig) -> str:
    host = f"127.0.0.1:{cfg.gateway.port}" if cfg.gateway.host in ("127.0.0.1", "0.0.0.0", "localhost") else f"{cfg.gateway.host}:{cfg.gateway.port}"
    return f"http://{host}"


def finish_client(paths: ClientPaths, start_service: bool | None) -> None:
    from mensarium.client.gateway import auth

    cfg = load_client_config(paths)
    if start_service is None:
        start_service = ask(questionary.confirm("Run the client as background services?", default=True, style=STYLE))
    units: list[tuple[service.Unit, bool]] = [("client", cfg.worker.enabled), ("gateway", cfg.gateway.enabled)]
    if start_service:
        for unit, enabled in units:
            if enabled:
                with console.status(f"Starting the {unit}..."):
                    how = service.install(unit)
                    time.sleep(2)
                if service.is_running(unit):
                    ok(f"{unit} is running ({how})")
                else:
                    warn(f"{unit} may not be running; check {service.log_file(unit)}")
            elif service.is_installed(unit):
                service.uninstall(unit)
                ok(f"{unit} service removed")
    if cfg.worker.enabled:
        _desktop_setup()
    rows = [
        ("Name", cfg.name),
        ("Client ID", cfg.target_id),
        ("Core", cfg.server),
        ("Worker", "enabled" if cfg.worker.enabled else "disabled"),
        ("Roots", ", ".join(cfg.roots)),
        ("Programs", ", ".join(cfg.command_allowlist)),
        ("Full access", "allowed" if cfg.allow_full_access else "disabled"),
        ("Bash scripts", "allowed" if cfg.allow_shell else "disabled"),
        ("Gateway", f"{_gateway_url(cfg)} ({'all interfaces' if cfg.gateway.host == '0.0.0.0' else 'this machine only'})" if cfg.gateway.enabled else "disabled"),
        ("Logs", str(service.log_file("client").parent)),
    ]
    footer = "The device appears as online in the web UI within a few seconds."
    if cfg.gateway.enabled:
        footer = (
            f"Open the web UI: {_gateway_url(cfg)}/login?link={auth.write_link(paths)} (one-time link)\n"
            "Later: mensarium client gateway open, token: mensarium client gateway token"
        )
    if not start_service:
        footer += "\nStart manually: mensarium client run" + (", mensarium client gateway run" if cfg.gateway.enabled else "")
    summary("Mensarium client is ready", rows, footer=footer)


def core_status() -> None:
    paths = CorePaths()
    cfg = load_config(paths)
    healthy = wait_healthy(f"http://127.0.0.1:{cfg.server.port}", timeout_s=2)
    summary(
        "Mensarium Core",
        [
            ("Core", "running" if healthy else "not responding"),
            ("Core URL", cfg.server.public_url),
            ("Provider", f"{cfg.llm.active_provider} / {cfg.llm.providers[cfg.llm.active_provider].default_model}"),
            ("Device", f"{device_name(cfg)}: {', '.join(cfg.device.roots) or '~'}" if cfg.device.enabled else "disabled"),
            ("Service", ("running" if service.is_running("core") else "stopped") if service.is_installed("core") else "not installed"),
            ("Data", str(paths.root)),
        ],
        footer="Open the web UI: mensarium core open\nPair another device: mensarium core pair-code\nReconfigure: mensarium core setup\nAll commands: mensarium core --help",
    )


def client_status() -> None:
    paths = ClientPaths()
    cfg = load_client_config(paths)
    unit_state = lambda unit: ("running" if service.is_running(unit) else "stopped") if service.is_installed(unit) else "not installed"  # noqa: E731
    rows = [
        ("Name", cfg.name),
        ("Client ID", cfg.target_id),
        ("Core", cfg.server),
        ("Worker", unit_state("client") if cfg.worker.enabled else "disabled"),
        ("Gateway", f"{_gateway_url(cfg)}, {unit_state('gateway')}" if cfg.gateway.enabled else "disabled"),
    ]
    summary(
        "Mensarium client",
        rows,
        footer=("Open the web UI: mensarium client gateway open\n" if cfg.gateway.enabled else "")
        + "Reconfigure: mensarium client setup\nThe Core moved: mensarium client move <url>\nAll commands: mensarium client --help",
    )
