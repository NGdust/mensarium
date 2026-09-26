"""Local login of the gateway: a token kept on this machine and one-time links for `gateway open`."""

import hmac
import secrets

from mensarium.client.config import ClientPaths
from mensarium.shared.paths import write_private

COOKIE = "mensarium_gateway"


def load_or_create_token(paths: ClientPaths) -> str:
    if paths.gateway_token.exists():
        return paths.gateway_token.read_text().strip()
    return rotate_token(paths)


def rotate_token(paths: ClientPaths) -> str:
    token = secrets.token_urlsafe(24)
    write_private(paths.gateway_token, token)
    return token


def check_token(paths: ClientPaths, candidate: str) -> bool:
    return hmac.compare_digest(candidate.strip(), load_or_create_token(paths))


def write_link(paths: ClientPaths) -> str:
    """A nonce for a login link; the gateway accepts it once and deletes the file."""
    nonce = secrets.token_urlsafe(24)
    write_private(paths.gateway_link, nonce)
    return nonce


def take_link(paths: ClientPaths, nonce: str) -> bool:
    if not paths.gateway_link.exists():
        return False
    stored = paths.gateway_link.read_text().strip()
    paths.gateway_link.unlink(missing_ok=True)
    return hmac.compare_digest(stored, nonce)
