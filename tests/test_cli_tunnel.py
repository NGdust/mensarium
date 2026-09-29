import asyncio
import base64
import json
import tempfile
import unittest
from pathlib import Path

import websockets
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from mensarium.client.config import ClientConfig, ClientPaths
from mensarium.client.gateway.tunnel import Tunnel


class CliTunnelTests(unittest.IsolatedAsyncioTestCase):
    async def test_tunnel_call_returns_status_and_body(self) -> None:
        async def core(ws: websockets.ServerConnection) -> None:
            await ws.send(json.dumps({"type": "auth.challenge", "nonce": "n"}))
            json.loads(await ws.recv())
            hello = json.loads(await ws.recv())
            assert hello["session"] == "cli"
            await ws.send(json.dumps({"type": "auth.ok", "ts": ""}))
            req = json.loads(await ws.recv())
            body = base64.b64encode(b'{"ok":true}').decode()
            await ws.send(json.dumps({"type": "api.response", "id": req["id"], "status": 200, "headers": {}, "body": body}))
            await ws.send(json.dumps({"type": "api.end", "id": req["id"]}))

        async with websockets.serve(core, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            cfg = ClientConfig(
                server=f"http://127.0.0.1:{port}", ws_url=f"ws://127.0.0.1:{port}", target_id="tgt_1", workspace_id="ws", name="n",
                core_public_key="", core_fingerprint="", roots=[], command_allowlist=[],
            )
            tunnel = Tunnel(cfg, ClientPaths(Path(tempfile.mkdtemp())), Ed25519PrivateKey.generate(), session="cli")
            status, body = await asyncio.wait_for(tunnel.call("GET", "/v1/projects"), 10)
        self.assertEqual((status, body), (200, b'{"ok":true}'))


if __name__ == "__main__":
    unittest.main()
