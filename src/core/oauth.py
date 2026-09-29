"""OAuth 2.1 for plugins: discovery and dynamic registration on MCP servers (RFC 9728, 8414, 7591), PKCE,
code exchange and refresh. Tokens are handled by the plugin manager; this module only talks to the provider."""

import base64
import hashlib
import html
import logging
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

log = logging.getLogger("mensarium.core.oauth")

PENDING_TTL_S = 600
CLIENT_NAME = "Mensarium"
DEFAULT_EXPIRES_S = 3600


class OAuthError(Exception):
    pass


class InvalidGrant(OAuthError):
    """The refresh token is gone: the user has to sign in again."""


@dataclass
class Endpoints:
    issuer: str
    authorize: str
    token: str
    register: str | None = None
    revoke: str | None = None


@dataclass
class Pending:
    plugin_id: str
    verifier: str
    redirect_uri: str
    endpoints: Endpoints
    client_id: str
    client_secret: str | None
    resource: str | None
    expires: float


def _origin(url: str) -> str:
    u = urlparse(url)
    return f"{u.scheme}://{u.netloc}"


def _www_authenticate(value: str) -> dict[str, str]:
    return {m.group(1): m.group(2) for m in re.finditer(r'(\w+)="([^"]*)"', value)}


class OAuthFlow:
    def __init__(self, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.transport = transport
        self.pending: dict[str, Pending] = {}

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=20, follow_redirects=False, transport=self.transport)

    async def _json(self, client: httpx.AsyncClient, url: str) -> dict[str, Any] | None:
        try:
            resp = await client.get(url, headers={"Accept": "application/json"})
        except httpx.HTTPError as e:
            raise OAuthError(f"cannot reach {url}: {e}") from e
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    async def discover(self, mcp_url: str) -> Endpoints:
        """The authorization server of an MCP server: from its protected-resource metadata, else its origin."""
        async with self._client() as client:
            issuer = _origin(mcp_url)
            try:
                probe = await client.post(mcp_url, json={"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}},
                                          headers={"Accept": "application/json, text/event-stream"})
            except httpx.HTTPError as e:
                raise OAuthError(f"cannot reach {mcp_url}: {e}") from e
            prm_url = _www_authenticate(probe.headers.get("www-authenticate", "")).get("resource_metadata")
            prm = await self._json(client, prm_url) if prm_url else None
            if prm is None:
                prm = await self._json(client, f"{issuer}/.well-known/oauth-protected-resource")
            if prm and prm.get("authorization_servers"):
                issuer = str(prm["authorization_servers"][0]).rstrip("/")
            meta = await self._json(client, f"{issuer}/.well-known/oauth-authorization-server")
            if meta is None:
                meta = await self._json(client, f"{issuer}/.well-known/openid-configuration")
            if not meta or not meta.get("authorization_endpoint") or not meta.get("token_endpoint"):
                raise OAuthError(f"{issuer} does not publish OAuth metadata")
            methods = meta.get("code_challenge_methods_supported")
            if methods and "S256" not in methods:
                raise OAuthError(f"{issuer} does not support PKCE S256")
            return Endpoints(
                issuer=str(meta.get("issuer") or issuer),
                authorize=str(meta["authorization_endpoint"]),
                token=str(meta["token_endpoint"]),
                register=meta.get("registration_endpoint"),
                revoke=meta.get("revocation_endpoint"),
            )

    async def register(self, ep: Endpoints, redirect_uri: str) -> tuple[str, str | None]:
        if not ep.register:
            raise OAuthError(f"{ep.issuer} does not support automatic client registration; this plugin needs a token instead")
        body = {
            "client_name": CLIENT_NAME,
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
        async with self._client() as client:
            try:
                resp = await client.post(ep.register, json=body)
            except httpx.HTTPError as e:
                raise OAuthError(f"registration failed: {e}") from e
        if resp.status_code not in (200, 201):
            raise OAuthError(f"registration failed: HTTP {resp.status_code} {resp.text[:200]}")
        data = resp.json()
        if not data.get("client_id"):
            raise OAuthError("registration answer has no client_id")
        return str(data["client_id"]), data.get("client_secret") or None

    def begin(
        self,
        plugin_id: str,
        ep: Endpoints,
        client_id: str,
        client_secret: str | None,
        redirect_uri: str,
        scopes: list[str],
        resource: str | None,
        params: dict[str, str],
    ) -> str:
        now = time.monotonic()
        self.pending = {k: v for k, v in self.pending.items() if v.expires > now and v.plugin_id != plugin_id}
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        state = secrets.token_urlsafe(32)
        self.pending[state] = Pending(plugin_id, verifier, redirect_uri, ep, client_id, client_secret, resource, now + PENDING_TTL_S)
        query = {
            **params,
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        if scopes:
            query["scope"] = " ".join(scopes)
        if resource:
            query["resource"] = resource
        sep = "&" if "?" in ep.authorize else "?"
        return f"{ep.authorize}{sep}{urlencode(query)}"

    def take(self, state: str) -> Pending:
        p = self.pending.pop(state, None)
        if p is None or p.expires < time.monotonic():
            raise OAuthError("this sign-in link has expired; start again from Settings")
        return p

    async def _token_request(self, url: str, form: dict[str, str], client_id: str, client_secret: str | None) -> dict[str, Any]:
        form = {**form, "client_id": client_id}
        if client_secret:
            form["client_secret"] = client_secret
        async with self._client() as client:
            try:
                resp = await client.post(url, data=form, headers={"Accept": "application/json"})
            except httpx.HTTPError as e:
                raise OAuthError(f"token request failed: {e}") from e
        try:
            data = resp.json() if "json" in resp.headers.get("content-type", "") else {k: v[0] for k, v in parse_qs(resp.text).items()}
        except ValueError:
            data = {}
        if resp.status_code != 200 or not data.get("access_token"):
            err = str(data.get("error_description") or data.get("error") or f"HTTP {resp.status_code}")
            raise InvalidGrant(err) if data.get("error") == "invalid_grant" else OAuthError(err)
        return {
            "access_token": data["access_token"],
            "refresh_token": data.get("refresh_token") or form.get("refresh_token") or "",
            "token_type": data.get("token_type") or "Bearer",
            "scope": data.get("scope") or form.get("scope", ""),
            "expires_at": time.time() + float(data.get("expires_in") or DEFAULT_EXPIRES_S),
        }

    async def exchange(self, p: Pending, code: str) -> dict[str, Any]:
        form = {"grant_type": "authorization_code", "code": code, "redirect_uri": p.redirect_uri, "code_verifier": p.verifier}
        if p.resource:
            form["resource"] = p.resource
        return await self._token_request(p.endpoints.token, form, p.client_id, p.client_secret)

    async def refresh(self, token_url: str, client_id: str, client_secret: str | None, refresh_token: str, resource: str | None) -> dict[str, Any]:
        form = {"grant_type": "refresh_token", "refresh_token": refresh_token}
        if resource:
            form["resource"] = resource
        return await self._token_request(token_url, form, client_id, client_secret)

    async def revoke(self, url: str | None, client_id: str, client_secret: str | None, token: str) -> None:
        if not url or not token:
            return
        form = {"token": token, "token_type_hint": "refresh_token", "client_id": client_id}
        if client_secret:
            form["client_secret"] = client_secret
        try:
            async with self._client() as client:
                await client.post(url, data=form)
        except httpx.HTTPError as e:
            log.info("token revocation skipped", extra={"error": str(e)})


def callback_page(ok: bool, plugin_id: str, message: str) -> str:
    title = "Connected" if ok else "Sign-in failed"
    text = html.escape(message)
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font:16px/1.5 system-ui,sans-serif;background:#111014;color:#eee;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}}
main{{max-width:28rem;padding:2rem;text-align:center}}h1{{font-size:1.25rem}}</style></head>
<body><main><h1>{title}</h1><p>{text}</p></main>
<script>
try {{ window.opener && window.opener.postMessage({{mensarium: "oauth", plugin: {plugin_id!r}, ok: {str(ok).lower()}}}, "*"); }} catch (e) {{}}
if ({str(ok).lower()}) setTimeout(() => window.close(), 1500);
</script></body></html>"""
