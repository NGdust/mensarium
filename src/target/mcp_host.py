import asyncio
import json
import logging
from pathlib import Path

from mensarium.contracts.protocol import McpServerDef, McpServerStatus, McpToolInfo
from mensarium.shared.paths import mensarium_home, write_private
from mensarium.target.config import TargetConfig
from mensarium.tool_runtime.mcp import McpClient, McpError, McpServer, connect, describe

log = logging.getLogger(__name__)

START_TIMEOUT_S = 240


class McpHost:
    """MCP servers the Core placed on this device; each program must be in the device's command allowlist."""

    def __init__(self, cfg: TargetConfig, roots: list[Path], status_file: Path) -> None:
        self.cfg = cfg
        self.roots = roots
        self.status_file = status_file
        self.clients: dict[str, McpClient] = {}
        self.defs: dict[str, McpServerDef] = {}
        self.lock = asyncio.Lock()

    def _refuse(self, d: McpServerDef) -> str | None:
        allow = self.cfg.command_allowlist
        if d.transport == "stdio" and "*" not in allow and d.command not in allow:
            return f"program {d.command!r} is not in this device's command allowlist"
        if d.cwd:
            cwd = Path(d.cwd).expanduser().resolve()
            if not any(cwd == r or cwd.is_relative_to(r) for r in self.roots):
                return f"folder {d.cwd} is outside the device's allowed folders"
        return None

    async def apply(self, servers: list[McpServerDef]) -> list[McpServerStatus]:
        async with self.lock:
            wanted = {d.name: d for d in servers}
            for name in list(self.clients):
                if wanted.get(name) != self.defs.get(name):
                    await self.clients.pop(name).close()
                    self.defs.pop(name, None)
            out: list[McpServerStatus] = []
            for name, d in wanted.items():
                if reason := self._refuse(d):
                    out.append(McpServerStatus(name=name, state="rejected", error=reason))
                    continue
                client = self.clients.get(name)
                if client is None:
                    client = connect(
                        McpServer(
                            name=name, transport=d.transport, command=d.command, args=d.args, env=d.env,
                            url=d.url, headers=d.headers, cwd=d.cwd or str(self.roots[0]),
                        ),
                        extra_path=[str(mensarium_home() / "bin")],
                    )
                    try:
                        await asyncio.wait_for(client.start(), START_TIMEOUT_S)
                    except (McpError, TimeoutError, OSError) as e:
                        await client.close()
                        out.append(McpServerStatus(name=name, state="error", error=str(e) or type(e).__name__))
                        continue
                    self.clients[name] = client
                    self.defs[name] = d
                out.append(McpServerStatus(name=name, state="ok", tools=[McpToolInfo(**t) for t in describe(client.tools)]))
            write_private(self.status_file, json.dumps([s.model_dump() for s in out], ensure_ascii=False, indent=1))
            return out

    def risk(self, server: str) -> str | None:
        d = self.defs.get(server)
        return d.risk if d else None

    async def call(self, server: str, tool: str, arguments: dict[str, object], timeout: float) -> tuple[str, bool]:
        client = self.clients.get(server)
        if client is None:
            raise McpError(f"MCP server {server!r} is not running on this device")
        return await client.call(tool, dict(arguments), timeout=timeout)

    async def close(self) -> None:
        for client in self.clients.values():
            await client.close()
        self.clients.clear()
        self.defs.clear()
