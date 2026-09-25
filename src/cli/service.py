import os
import shutil
import subprocess
import sys
from importlib import resources
from pathlib import Path
from typing import Literal

from mensarium import __version__
from mensarium.shared.paths import mensarium_home

Role = Literal["core", "target"]
COMMANDS: dict[str, list[str]] = {"core": ["core", "serve"], "target": ["target", "run"]}
APP_BUNDLE_ID = "com.mensarium.agent"
INFO_PLIST = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Mensarium</string>
<key>CFBundleIdentifier</key><string>{bundle_id}</string>
<key>CFBundleName</key><string>Mensarium</string>
<key>CFBundleDisplayName</key><string>Mensarium</string>
<key>CFBundleIconFile</key><string>AppIcon</string>
<key>CFBundlePackageType</key><string>APPL</string>
<key>CFBundleShortVersionString</key><string>{version}</string>
<key>CFBundleVersion</key><string>{version}</string>
<key>LSUIElement</key><true/>
<key>NSHighResolutionCapable</key><true/>
<key>NSAppleEventsUsageDescription</key><string>Mensarium operates apps on this Mac when you ask the agent to.</string>
</dict></plist>
"""


def app_bundle() -> Path:
    return Path.home() / "Applications" / "Mensarium.app"


def install_app_bundle() -> Path | None:
    """Mensarium.app around a tiny launcher that runs the agent as its child, so macOS shows Mensarium with its icon
    in Privacy & Security instead of the Python interpreter. Returns the launcher path, or None off macOS."""
    if sys.platform != "darwin":
        return None
    src = Path(str(resources.files("mensarium.target") / "macos"))
    launcher = src / "Mensarium"
    if not launcher.exists():
        return None
    app = app_bundle()
    macos, res = app / "Contents" / "MacOS", app / "Contents" / "Resources"
    macos.mkdir(parents=True, exist_ok=True)
    res.mkdir(parents=True, exist_ok=True)
    target = macos / "Mensarium"
    if not target.exists() or target.read_bytes() != launcher.read_bytes():
        shutil.copy2(launcher, target)
    target.chmod(0o755)
    icon = src / "AppIcon.icns"
    if icon.exists():
        shutil.copy2(icon, res / "AppIcon.icns")
    (app / "Contents" / "Info.plist").write_text(INFO_PLIST.format(bundle_id=APP_BUNDLE_ID, version=__version__))
    return target


def mensarium_bin() -> str:
    candidate = Path(sys.executable).parent / "mensarium"
    return str(candidate) if candidate.exists() else (shutil.which("mensarium") or "mensarium")


def log_file(role: Role) -> Path:
    path = mensarium_home() / role / f"{role}.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _label(role: Role) -> str:
    return f"com.mensarium.{role}"


def _plist_path(role: Role) -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{_label(role)}.plist"


def _unit_name(role: Role) -> str:
    return f"mensarium-{role}.service"


def _is_root() -> bool:
    return os.geteuid() == 0


def _systemd_user_dir() -> Path:
    return Path("/etc/systemd/system") if _is_root() else Path.home() / ".config" / "systemd" / "user"


def _systemctl(*args: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return _run("systemctl", *([] if _is_root() else ["--user"]), *args, check=check)


def backend() -> str:
    if sys.platform == "darwin":
        return "launchd"
    if shutil.which("systemctl") and Path("/run/systemd/system").exists():
        return "systemd"
    return "nohup"


def _run(*cmd: str, check: bool = False) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def install(role: Role) -> str:
    argv = [mensarium_bin(), *COMMANDS[role]]
    if role == "target" and (launcher := install_app_bundle()):
        argv = [str(launcher), *argv]
    env = {"MENSARIUM_HOME": str(mensarium_home()), "PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    log = log_file(role)
    kind = backend()
    if kind == "launchd":
        args = "".join(f"<string>{a}</string>" for a in argv)
        envs = "".join(f"<key>{k}</key><string>{v}</string>" for k, v in env.items())
        plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>{_label(role)}</string>
<key>ProgramArguments</key><array>{args}</array>
<key>EnvironmentVariables</key><dict>{envs}</dict>
<key>RunAtLoad</key><true/>
<key>KeepAlive</key><true/>
<key>StandardOutPath</key><string>{log}</string>
<key>StandardErrorPath</key><string>{log}</string>
</dict></plist>
"""
        path = _plist_path(role)
        path.parent.mkdir(parents=True, exist_ok=True)
        domain = f"gui/{os.getuid()}"
        _run("launchctl", "bootout", f"{domain}/{_label(role)}")
        path.write_text(plist)
        _run("launchctl", "bootstrap", domain, str(path), check=True)
        return f"launchd agent {_label(role)}"
    if kind == "systemd":
        envs = "\n".join(f'Environment="{k}={v}"' for k, v in env.items())
        unit = f"""[Unit]
Description=Mensarium {role}
After=network-online.target

[Service]
ExecStart={" ".join(argv)}
{envs}
Restart=always
RestartSec=3
StandardOutput=append:{log}
StandardError=append:{log}

[Install]
WantedBy={'multi-user.target' if _is_root() else 'default.target'}
"""
        d = _systemd_user_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / _unit_name(role)).write_text(unit)
        _systemctl("daemon-reload", check=True)
        _systemctl("enable", "--now", _unit_name(role), check=True)
        _systemctl("restart", _unit_name(role))
        if not _is_root() and shutil.which("loginctl"):
            _run("loginctl", "enable-linger", os.environ.get("USER", ""))
        return f"systemd unit {_unit_name(role)}"
    stop(role)
    with log.open("a") as out:
        proc = subprocess.Popen(argv, stdout=out, stderr=out, start_new_session=True, env={**os.environ, **env})
    (mensarium_home() / role / f"{role}.pid").write_text(str(proc.pid))
    return f"background process (pid {proc.pid}); it will not restart after reboot"


def stop(role: Role) -> None:
    kind = backend()
    if kind == "launchd":
        _run("launchctl", "bootout", f"gui/{os.getuid()}/{_label(role)}")
    elif kind == "systemd":
        _systemctl("stop", _unit_name(role))
    else:
        pid_file = mensarium_home() / role / f"{role}.pid"
        if pid_file.exists():
            try:
                os.kill(int(pid_file.read_text()), 15)
            except (ProcessLookupError, ValueError):
                pass
            pid_file.unlink(missing_ok=True)


def restart(role: Role) -> None:
    kind = backend()
    if kind == "launchd":
        _run("launchctl", "kickstart", "-k", f"gui/{os.getuid()}/{_label(role)}")
    elif kind == "systemd":
        _systemctl("restart", _unit_name(role))
    else:
        install(role)


def uninstall(role: Role) -> None:
    stop(role)
    kind = backend()
    if kind == "launchd":
        _plist_path(role).unlink(missing_ok=True)
        if role == "target":
            shutil.rmtree(app_bundle(), ignore_errors=True)
    elif kind == "systemd":
        _systemctl("disable", _unit_name(role))
        (_systemd_user_dir() / _unit_name(role)).unlink(missing_ok=True)
        _systemctl("daemon-reload")


def is_installed(role: Role) -> bool:
    kind = backend()
    if kind == "launchd":
        return _plist_path(role).exists()
    if kind == "systemd":
        return (_systemd_user_dir() / _unit_name(role)).exists()
    return (mensarium_home() / role / f"{role}.pid").exists()


def is_running(role: Role) -> bool:
    kind = backend()
    if kind == "launchd":
        out = _run("launchctl", "print", f"gui/{os.getuid()}/{_label(role)}").stdout
        return "state = running" in out
    if kind == "systemd":
        return _systemctl("is-active", _unit_name(role)).stdout.strip() == "active"
    pid_file = mensarium_home() / role / f"{role}.pid"
    if not pid_file.exists():
        return False
    try:
        os.kill(int(pid_file.read_text()), 0)
    except (ProcessLookupError, ValueError):
        return False
    return True
