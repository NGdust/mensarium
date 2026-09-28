"""The Core host as a device: a worker inside the Core process, attached over loopback like any client.

It reuses the client's agent, keys and login token under `core/device`, so every frame is signed and
verified exactly as for a remote device; there is no second execution path.
"""

import shutil
import socket
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mensarium import __version__
from mensarium.client.agent import platform_id
from mensarium.client.config import ClientConfig, ClientPaths, load_client_config, save_client_config
from mensarium.core.config import CoreConfig, CorePaths, save_config
from mensarium.core.repo import Repo
from mensarium.shared.crypto import fingerprint, load_or_create_private_key, public_key_b64
from mensarium.shared.ids import new_id
from mensarium.shared.paths import mensarium_home
from mensarium.shared.timeutil import now_iso

ADOPTED_DIR = "client.adopted"


def loopback(cfg: CoreConfig) -> str:
    host = cfg.server.host
    return f"{'127.0.0.1' if host in ('0.0.0.0', '127.0.0.1', 'localhost', '::') else host}:{cfg.server.port}"


def device_name(cfg: CoreConfig) -> str:
    return cfg.device.name or socket.gethostname().split(".")[0]


def device_roots(cfg: CoreConfig) -> list[str]:
    roots = [str(p) for p in (Path(r).expanduser().resolve() for r in cfg.device.roots) if p.is_dir()]
    return roots or [str(Path.home())]


def _apply(tcfg: ClientConfig, cfg: CoreConfig, core_public_key: str) -> ClientConfig:
    """The device follows the Core config; only its identity lives in device/config.yaml."""
    base = loopback(cfg)
    tcfg.server, tcfg.ws_url = f"http://{base}", f"ws://{base}/v1/clients/ws"
    tcfg.name = device_name(cfg)
    tcfg.core_public_key, tcfg.core_fingerprint = core_public_key, fingerprint(core_public_key)
    tcfg.roots = device_roots(cfg)
    tcfg.command_allowlist = list(cfg.device.command_allowlist)
    tcfg.allow_full_access = cfg.device.allow_full_access
    tcfg.allow_shell = cfg.device.allow_shell
    tcfg.allow_remote_plugins = cfg.device.allow_remote_plugins
    tcfg.allow_remote_update = False
    tcfg.worker.enabled = True
    tcfg.gateway.enabled = False
    return tcfg


async def ensure_device(
    repo: Repo, paths: CorePaths, cfg: CoreConfig, core_public_key: str, workspace_id: str
) -> tuple[ClientConfig, Ed25519PrivateKey] | None:
    """Register the Core host as a device without a pairing code; returns None when disabled."""
    if not cfg.device.enabled:
        return None
    dpaths = paths.device
    dpaths.ensure()
    if (ccfg := adoptable_client(paths, core_public_key)) is not None:
        cfg = adopt_client(paths, cfg, ccfg)
        await repo.audit(workspace_id, "core", "target.adopted", {"target_id": ccfg.target_id, "name": ccfg.name})
    key = load_or_create_private_key(dpaths.key)
    if dpaths.config.exists():
        tcfg = _apply(load_client_config(dpaths), cfg, core_public_key)
        row = await repo.get_target(tcfg.target_id)
        if row and row["status"] != "revoked":
            save_client_config(dpaths, tcfg)
            await repo.update_target(tcfg.target_id, {"name": tcfg.name, "public_key": public_key_b64(key)})
            return tcfg, key
    target_id = new_id("tgt")
    await repo.create_target(
        {
            "id": target_id,
            "workspace_id": workspace_id,
            "name": device_name(cfg),
            "platform": platform_id(),
            "hostname": socket.gethostname(),
            "status": "offline",
            "public_key": public_key_b64(key),
            "agent_version": __version__,
            "created_at": now_iso(),
        }
    )
    tcfg = _apply(
        ClientConfig(
            server="", ws_url="", target_id=target_id, workspace_id=workspace_id, name="",
            core_public_key=core_public_key, core_fingerprint="", roots=[],
        ),  # fmt: skip
        cfg,
        core_public_key,
    )
    save_client_config(dpaths, tcfg)
    await repo.audit(workspace_id, "core", "target.paired", {"target_id": target_id, "name": tcfg.name, "core_host": True})
    return tcfg, key


def adoptable_client(paths: CorePaths, core_public_key: str) -> ClientConfig | None:
    """A client paired with this very Core on the same machine: since 0.49 the Core is that device itself."""
    cpaths = ClientPaths()
    if paths.device.config.exists() or not cpaths.config.exists():
        return None
    ccfg = load_client_config(cpaths)
    return ccfg if ccfg.core_public_key == core_public_key else None


def adopt_client(paths: CorePaths, cfg: CoreConfig, ccfg: ClientConfig) -> CoreConfig:
    """Move the client's identity, token and settings into the Core and retire its services; the client directory is kept aside."""
    from mensarium.cli import service

    for role in ("client", "gateway"):
        if service.is_installed(role):  # type: ignore[arg-type]
            service.uninstall(role)  # type: ignore[arg-type]
    cpaths = ClientPaths()
    dpaths = paths.device
    dpaths.ensure()
    for src, dst in (
        (cpaths.key, dpaths.key),
        (cpaths.gateway_token, dpaths.gateway_token),
        (cpaths.permissions, dpaths.permissions),
        (cpaths.plugins, dpaths.plugins),
        (cpaths.audit, dpaths.audit),
    ):
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            dst.chmod(0o600)
    cfg.device.enabled = True
    cfg.device.name = ccfg.name
    cfg.device.roots = list(ccfg.roots)
    cfg.device.command_allowlist = list(ccfg.command_allowlist)
    cfg.device.allow_full_access = ccfg.allow_full_access
    cfg.device.allow_shell = ccfg.allow_shell
    cfg.device.allow_remote_plugins = ccfg.allow_remote_plugins
    save_config(paths, cfg)
    save_client_config(dpaths, _apply(ccfg, cfg, ccfg.core_public_key))
    aside = mensarium_home() / ADOPTED_DIR
    shutil.rmtree(aside, ignore_errors=True)
    cpaths.root.rename(aside)
    return cfg
