import socket
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mensarium import __version__
from mensarium.core.config import CoreConfig, CorePaths
from mensarium.core.repo import Repo
from mensarium.shared.crypto import fingerprint, load_or_create_private_key, public_key_b64
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import now_iso
from mensarium.target.agent import platform_id
from mensarium.target.config import TargetConfig, TargetPaths, load_target_config, save_target_config


def local_target_paths(paths: CorePaths) -> TargetPaths:
    return TargetPaths(paths.root / "local-target")


def _roots(cfg: CoreConfig) -> list[str]:
    return [str(p) for p in (Path(r).expanduser().resolve() for r in cfg.local_target.roots) if p.is_dir()]


async def ensure_local_target(
    repo: Repo, paths: CorePaths, cfg: CoreConfig, core_public_key: str, workspace_id: str
) -> tuple[TargetConfig, Ed25519PrivateKey] | None:
    """Register the Core host as a target so it is always available, without a pairing code."""
    roots = _roots(cfg)
    if not cfg.local_target.enabled or not roots:
        return None
    tpaths = local_target_paths(paths)
    tpaths.ensure()
    key = load_or_create_private_key(tpaths.key)
    base = f"127.0.0.1:{cfg.server.port}"

    if tpaths.config.exists():
        tcfg = load_target_config(tpaths)
        row = await repo.get_target(tcfg.target_id)
        if row and row["status"] == "revoked":
            return None
        if row:
            tcfg.roots = roots
            tcfg.allow_full_access = cfg.local_target.allow_full_access
            tcfg.allow_shell = cfg.local_target.allow_shell
            tcfg.server, tcfg.ws_url = f"http://{base}", f"ws://{base}/v1/targets/ws"
            save_target_config(tpaths, tcfg)
            return tcfg, key

    name = socket.gethostname().split(".")[0]
    target_id = new_id("tgt")
    await repo.create_target(
        {
            "id": target_id,
            "workspace_id": workspace_id,
            "name": name,
            "platform": platform_id(),
            "hostname": socket.gethostname(),
            "status": "offline",
            "public_key": public_key_b64(key),
            "agent_version": __version__,
            "created_at": now_iso(),
        }
    )
    tcfg = TargetConfig(
        server=f"http://{base}",
        ws_url=f"ws://{base}/v1/targets/ws",
        target_id=target_id,
        workspace_id=workspace_id,
        name=name,
        core_public_key=core_public_key,
        core_fingerprint=fingerprint(core_public_key),
        roots=roots,
        allow_full_access=cfg.local_target.allow_full_access,
        allow_shell=cfg.local_target.allow_shell,
    )
    save_target_config(tpaths, tcfg)
    await repo.audit(workspace_id, "core", "target.paired", {"target_id": target_id, "name": name, "local": True})
    return tcfg, key
