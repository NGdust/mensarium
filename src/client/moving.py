"""Following the Core to a new address: the old Core announces it, the new one proves it holds the same key."""

import secrets

import httpx
from pydantic import ValidationError

from mensarium.client.config import ClientConfig, ClientPaths, load_client_config, save_client_config
from mensarium.contracts.protocol import CoreIdentity, CoreMoved
from mensarium.shared.crypto import verify
from mensarium.shared.timeutil import parse_iso, utcnow


class MoveError(Exception):
    pass


def accept(cfg: ClientConfig, raw: dict[str, object]) -> CoreMoved | None:
    """A `core.moved` frame this client may act on: signed by its Core, addressed to it and not expired."""
    try:
        msg = CoreMoved.model_validate(raw)
    except ValidationError:
        return None
    if not verify(cfg.core_public_key, raw) or msg.target_id != cfg.target_id or parse_iso(msg.expires_at) < utcnow():
        return None
    if not msg.url.startswith(("http://", "https://")):
        return None
    return msg


def remember(paths: ClientPaths, url: str) -> None:
    """Keep the new address next to the old one; the switch happens only when the old Core stops answering."""
    cfg = load_client_config(paths)
    cfg.moved_to = url.rstrip("/")
    save_client_config(paths, cfg)


async def check(url: str, core_public_key: str) -> str:
    """Ask the Core at `url` to sign a fresh nonce with our Core's key; returns its WebSocket URL."""
    nonce = secrets.token_hex(16)
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            resp = await http.get(f"{url.rstrip('/')}/v1/core/identity", params={"nonce": nonce})
    except httpx.HTTPError as e:
        raise MoveError(f"cannot reach {url}: {e}") from e
    if resp.status_code != 200:
        raise MoveError(f"{url} is not a Mensarium Core that knows this move (HTTP {resp.status_code})")
    try:
        ident = CoreIdentity.model_validate(resp.json())
    except (ValidationError, ValueError) as e:
        raise MoveError(f"{url} gave an invalid identity answer") from e
    if ident.nonce != nonce or ident.core_public_key != core_public_key or not verify(core_public_key, resp.json()):
        raise MoveError(f"the Core at {url} is a different Core (its key does not match the one this client is paired with)")
    return ident.ws_url


async def switch(paths: ClientPaths, cfg: ClientConfig, url: str) -> None:
    """Point this client at the Core's new address after it proved its key; `cfg` is updated in place."""
    url = url.rstrip("/")
    ws_url = await check(url, cfg.core_public_key)
    disk = load_client_config(paths)
    disk.server, disk.ws_url, disk.moved_to = url, ws_url, None
    save_client_config(paths, disk)
    cfg.server, cfg.ws_url, cfg.moved_to = url, ws_url, None


async def follow(paths: ClientPaths, cfg: ClientConfig) -> bool:
    """Called when the Core is unreachable: pick up a switch done by the other process or make one; True if the address changed."""
    try:
        disk = load_client_config(paths)
    except (FileNotFoundError, ValidationError):
        return False
    if disk.server != cfg.server:
        cfg.server, cfg.ws_url, cfg.moved_to = disk.server, disk.ws_url, disk.moved_to
        return True
    if not disk.moved_to:
        return False
    try:
        await switch(paths, cfg, disk.moved_to)
    except MoveError:
        return False
    return True
