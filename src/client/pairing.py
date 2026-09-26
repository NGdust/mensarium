import socket
from pathlib import Path

import httpx

from mensarium import __version__
from mensarium.client.agent import platform_id
from mensarium.client.config import DEFAULT_COMMAND_ALLOWLIST, ClientConfig, ClientPaths, save_client_config
from mensarium.contracts.protocol import PairRequest, PairResponse
from mensarium.shared.crypto import load_or_create_private_key, public_key_b64


class PairingError(Exception):
    pass


def pair(
    paths: ClientPaths,
    *,
    server: str,
    code: str,
    name: str,
    roots: list[str],
    command_allowlist: list[str] | None = None,
    allow_full_access: bool = True,
    allow_remote_update: bool = True,
    allow_remote_plugins: bool = True,
    allow_shell: bool = True,
) -> ClientConfig:
    server = server.rstrip("/")
    resolved_roots = []
    for r in roots:
        p = Path(r).expanduser().resolve()
        if not p.is_dir():
            raise PairingError(f"root {r} is not a directory")
        resolved_roots.append(str(p))
    if not resolved_roots:
        raise PairingError("at least one workspace root is required")
    paths.ensure()
    key = load_or_create_private_key(paths.key)
    body = PairRequest(
        code=code,
        name=name,
        platform=platform_id(),
        hostname=socket.gethostname(),
        agent_version=__version__,
        public_key=public_key_b64(key),
    )
    try:
        resp = httpx.post(f"{server}/v1/targets/pair", json=body.model_dump(), timeout=20)
    except httpx.HTTPError as e:
        raise PairingError(f"cannot reach core at {server}: {e}") from e
    if resp.status_code != 200:
        detail = resp.json().get("detail") if resp.headers.get("content-type", "").startswith("application/json") else resp.text
        raise PairingError(f"core refused pairing ({resp.status_code}): {detail}")
    data = PairResponse.model_validate(resp.json())
    cfg = ClientConfig(
        server=server,
        ws_url=data.ws_url,
        target_id=data.target_id,
        workspace_id=data.workspace_id,
        name=name,
        core_public_key=data.core_public_key,
        core_fingerprint=data.core_fingerprint,
        roots=resolved_roots,
        command_allowlist=command_allowlist or list(DEFAULT_COMMAND_ALLOWLIST),
        allow_full_access=allow_full_access,
        allow_remote_update=allow_remote_update,
        allow_remote_plugins=allow_remote_plugins,
        allow_shell=allow_shell,
    )
    save_client_config(paths, cfg)
    return cfg
