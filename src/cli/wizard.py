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
    LLMConfig,
    ProviderConfig,
    ServerConfig,
    load_config,
    read_secret,
    save_config,
    write_secret,
)
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
    banner("Core setup: the main agent and LLM gateway (the web UI runs on clients)")
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

    total = 3
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

    paths.ensure()
    if api_key and api_key_ref:
        write_secret(paths, api_key_ref.removeprefix("secret://"), api_key)
    key = load_or_create_private_key(paths.signing_key)
    ok(f"Core signing key fingerprint: {fingerprint(public_key_b64(key))}")

    cfg = CoreConfig(
        server=ServerConfig(host=bind, port=port, public_url=public_url),
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
    step(3, total, "Service")
    _finish_core(paths, cfg, start_service)


def _finish_core(paths: CorePaths, cfg: CoreConfig, start_service: bool | None) -> None:
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
    summary(
        "Mensarium Core is ready",
        [
            ("Core URL", cfg.server.public_url),
            ("Provider", f"{cfg.llm.active_provider} / {cfg.llm.providers[cfg.llm.active_provider].default_model}"),
            ("Data", str(paths.root)),
            ("Logs", str(service.log_file("core"))),
        ],
        footer=(
            "The web UI opens on a client: install one with `curl -fsSL https://mensarium.com/install.sh | sh`,\n"
            "create a code with `mensarium core pair-code` here and run `mensarium client` there."
            + ("" if start_service else "\nStart manually: mensarium core serve")
        ),
    )


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
    banner("Client setup: this machine becomes a device of the Core")
    if paths.config.exists():
        current = load_client_config(paths)
        action = ask(
            questionary.select(
                f"This machine is already paired as '{current.name}' with {current.server}.",
                choices=["Keep the pairing and (re)start the agent", "Pair again (new code)"],
                style=STYLE,
            )
        )
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
    choices = [questionary.Choice(p, p, checked=i == 0) for i, p in enumerate(_root_candidates())]
    roots: list[str] = []
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
            style=STYLE,
        )
    )
    allowlist = list(DEFAULT_COMMAND_ALLOWLIST)
    if mode == "any":
        allowlist = ["*"]
    elif mode == "custom":
        raw = ask(questionary.text("Programs, comma separated:", default=", ".join(allowlist), style=STYLE))
        allowlist = [p.strip() for p in raw.split(",") if p.strip()]

    full_access = ask(
        questionary.confirm(
            "Allow full-access mode on this machine (the agent runs commands without asking when a chat is switched to it)?",
            default=True,
            style=STYLE,
        )
    )

    remote_update = ask(
        questionary.confirm(
            "Allow the Core to update this agent from its web UI (downloads the release from the Core and restarts the agent)?",
            default=True,
            style=STYLE,
        )
    )

    remote_plugins = ask(
        questionary.confirm(
            "Allow the Core to run MCP servers from plugins on this machine (programs must be in the list above)?",
            default=True,
            style=STYLE,
        )
    )

    allow_shell = ask(
        questionary.confirm(
            "Allow the agent to run bash scripts on this machine (each script is approved by you in the chat)?",
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
                    roots=roots,
                    command_allowlist=allowlist,
                    allow_full_access=full_access,
                    allow_remote_update=remote_update,
                    allow_remote_plugins=remote_plugins,
                    allow_shell=allow_shell,
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
            ("Service", ("running" if service.is_running("core") else "stopped") if service.is_installed("core") else "not installed"),
            ("Data", str(paths.root)),
        ],
        footer="Pair a client: mensarium core pair-code\nReconfigure: mensarium core setup\nAll commands: mensarium core --help",
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
        + "Reconfigure: mensarium client setup\nAll commands: mensarium client --help",
    )
