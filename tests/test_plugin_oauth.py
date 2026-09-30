import json
import tempfile
import time
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

from mensarium.contracts.plugins import Plugin
from mensarium.core.config import CorePaths
from mensarium.core.db import Database
from mensarium.core.oauth import OAuthFlow
from mensarium.core.plugins import Installed, PluginManager, builtin_specs
from mensarium.core.repo import Repo
from mensarium.plugins import bundled_catalog, google

CATALOG = {p.id: p for p in bundled_catalog()}
ORIGIN = "http://127.0.0.1:8787"
NOTION = "https://mcp.notion.com"


def notion_server(calls: list[str]):
    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(f"{req.method} {req.url.path}")
        if req.url.path == "/mcp":
            return httpx.Response(401, headers={"WWW-Authenticate": f'Bearer realm="OAuth", resource_metadata="{NOTION}/.well-known/oauth-protected-resource/mcp"'})
        if req.url.path == "/.well-known/oauth-protected-resource/mcp":
            return httpx.Response(200, json={"resource": NOTION, "authorization_servers": [NOTION]})
        if req.url.path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json={
                "issuer": NOTION, "authorization_endpoint": f"{NOTION}/authorize", "token_endpoint": f"{NOTION}/token",
                "registration_endpoint": f"{NOTION}/register", "code_challenge_methods_supported": ["S256"],
            })
        if req.url.path == "/register":
            body = json.loads(req.content)
            assert body["redirect_uris"] == [f"{ORIGIN}/v1/oauth/callback"]
            return httpx.Response(201, json={"client_id": "cid-1"})
        return httpx.Response(404)
    return handler


def google_token_server(calls: list[dict[str, str]]):
    def handler(req: httpx.Request) -> httpx.Response:
        form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
        calls.append(form)
        n = len(calls)
        return httpx.Response(200, json={"access_token": f"at{n}", "refresh_token": "rt", "expires_in": 3600, "scope": "https://www.googleapis.com/auth/gmail.readonly"})
    return handler


class OAuthTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = CorePaths(Path(self.tmp.name))
        self.paths.ensure()
        self.db = Database(self.paths.db)
        await self.db.connect()
        self.addAsyncCleanup(self.db.close)
        self.manager = PluginManager(Repo(self.db), self.paths, "ws")
        self.manager._connect = self._no_connect  # type: ignore[method-assign]

    async def _no_connect(self, plugin_id: str) -> None:
        pass

    async def test_start_discovers_registers_and_builds_url(self):
        calls: list[str] = []
        self.manager.oauth = OAuthFlow(transport=httpx.MockTransport(notion_server(calls)))
        await self.manager.install(CATALOG["mcp-notion"], "catalog")
        self.assertIn("_oauth", (await self.manager.get("mcp-notion")).missing())

        url = (await self.manager.oauth_start("mcp-notion", ORIGIN))["url"]

        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.assertTrue(url.startswith(f"{NOTION}/authorize?"))
        self.assertEqual(q["code_challenge_method"], "S256")
        self.assertEqual(q["client_id"], "cid-1")
        self.assertEqual(q["redirect_uri"], f"{ORIGIN}/v1/oauth/callback")
        self.assertEqual(q["resource"], f"{NOTION}/mcp")
        self.assertIn("POST /register", calls)
        self.assertEqual((await self.manager.get("mcp-notion")).config["_oauth_client"]["client_id"], "cid-1")
        # a second start with the same redirect reuses the registration
        await self.manager.oauth_start("mcp-notion", ORIGIN)
        self.assertEqual(calls.count("POST /register"), 1)
        self.assertEqual(len(self.manager.oauth.pending), 1)

    def test_redirect_prefers_loopback_over_plain_http(self):
        self.manager.core_port = 8799
        self.assertEqual(self.manager.redirect("https://core.example.com", "1.2.3.4"), ("https://core.example.com/v1/oauth/callback", False))
        self.assertEqual(self.manager.redirect("http://localhost:8790", "1.2.3.4"), ("http://localhost:8790/v1/oauth/callback", False))
        self.assertEqual(self.manager.redirect("http://194.87.128.55:8788", "1.2.3.4"), ("http://127.0.0.1:8799/v1/oauth/callback", True))
        self.manager.gateway_loopback = lambda ip: "http://127.0.0.1:8790" if ip == "1.2.3.4" else None
        self.assertEqual(self.manager.redirect("http://194.87.128.55:8788", "1.2.3.4"), ("http://127.0.0.1:8790/v1/oauth/callback", False))

    async def test_callback_stores_tokens_and_refreshes_expired(self):
        calls: list[dict[str, str]] = []
        self.manager.oauth = OAuthFlow(transport=httpx.MockTransport(google_token_server(calls)))
        await self.manager.install(CATALOG["google-gmail"], "catalog")
        await self.manager.configure("google-gmail", values={"client_id": "gid"}, secrets={"client_secret": "gsecret"})

        url = (await self.manager.oauth_start("google-gmail", ORIGIN))["url"]
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.assertEqual(q["scope"], "https://www.googleapis.com/auth/gmail.readonly")
        self.assertEqual(q["access_type"], "offline")

        plugin_id = await self.manager.oauth_finish(q["state"], "the-code")

        self.assertEqual(plugin_id, "google-gmail")
        self.assertEqual(calls[0]["grant_type"], "authorization_code")
        self.assertEqual(calls[0]["client_secret"], "gsecret")
        self.assertTrue(calls[0]["code_verifier"])
        inst = await self.manager.get("google-gmail")
        self.assertEqual(inst.missing(), [])
        self.assertEqual(inst.oauth["token_url"], "https://oauth2.googleapis.com/token")
        self.assertEqual(await self.manager.access_token(inst), "at1")
        self.assertEqual(len(calls), 1)

        tokens = json.loads((self.paths.secrets / "plugin-google-gmail-oauth").read_text())
        tokens["expires_at"] = time.time() - 1
        (self.paths.secrets / "plugin-google-gmail-oauth").write_text(json.dumps(tokens))

        self.assertEqual(await self.manager.access_token(inst), "at2")
        self.assertEqual(calls[1]["grant_type"], "refresh_token")
        self.assertEqual(calls[1]["refresh_token"], "rt")
        self.assertEqual(self.manager.view(inst.plugin, inst, None)["oauth"]["connected"], True)

        await self.manager.oauth_disconnect("google-gmail")
        self.assertFalse((self.paths.secrets / "plugin-google-gmail-oauth").exists())
        self.assertIn("_oauth", (await self.manager.get("google-gmail")).missing())

    async def test_slack_token_without_lifetime_does_not_expire(self):
        calls: list[dict[str, str]] = []

        def handler(req: httpx.Request) -> httpx.Response:
            calls.append({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
            return httpx.Response(200, json={"ok": True, "access_token": "xoxp-1", "token_type": "user"})

        self.manager.oauth = OAuthFlow(transport=httpx.MockTransport(handler))
        await self.manager.install(CATALOG["mcp-slack"], "catalog")
        await self.manager.configure("mcp-slack", values={"client_id": "1.2", "send": True}, secrets={"client_secret": "ssecret"})

        url = (await self.manager.oauth_start("mcp-slack", ORIGIN))["url"]
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        self.assertTrue(url.startswith("https://slack.com/oauth/v2_user/authorize?"))
        self.assertIn("chat:write", q["scope"].split())
        await self.manager.oauth_finish(q["state"], "the-code")

        inst = await self.manager.get("mcp-slack")
        self.assertEqual(calls[0]["client_secret"], "ssecret")
        self.assertIsNone(json.loads((self.paths.secrets / "plugin-mcp-slack-oauth").read_text())["expires_at"])
        self.assertEqual(await self.manager.access_token(inst), "xoxp-1")
        self.assertEqual(len(calls), 1)


class BuiltinToolTests(unittest.TestCase):
    def test_builtin_tools_follow_scope_and_switches(self):
        plugin: Plugin = CATALOG["google-gmail"]
        send = "https://www.googleapis.com/auth/gmail.send"

        def specs(scope: str, disabled: list[str] | None = None):
            return builtin_specs(Installed(plugin, {"enabled": 1, "config": {"_oauth": {"scope": scope}, "_disabled": disabled or []}}))

        self.assertEqual(set(specs("read-only-scope")), {"gmail.search", "gmail.read"})
        self.assertEqual(set(specs(send, ["gmail.read"])), {"gmail.search", "gmail.send"})
        full = specs(send)
        self.assertEqual(full["gmail.send"].risk, "network")
        self.assertEqual(full["gmail.search"].risk, "read")


class GmailTests(unittest.IsolatedAsyncioTestCase):
    async def test_gmail_search_formats_messages(self):
        def handler(req: httpx.Request) -> httpx.Response:
            self.assertEqual(req.headers["authorization"], "Bearer tok")
            if req.url.path.endswith("/messages"):
                return httpx.Response(200, json={"messages": [{"id": "m1"}]})
            return httpx.Response(200, json={"id": "m1", "snippet": "see attached", "payload": {"headers": [
                {"name": "From", "value": "alice@example.com"}, {"name": "Subject", "value": "Invoice"}, {"name": "Date", "value": "Mon, 1 Sep 2026"}]}})
        google.TRANSPORT = httpx.MockTransport(handler)
        self.addCleanup(setattr, google, "TRANSPORT", None)

        out = await google.gmail_search({"_access_token": "tok"}, {"query": "from:alice"})

        self.assertIn("id m1 | Mon, 1 Sep 2026 | from alice@example.com | Invoice", out)
        self.assertIn("see attached", out)
