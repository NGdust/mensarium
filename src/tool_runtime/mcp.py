"""Minimal Model Context Protocol client: stdio and streamable HTTP transports, tools only."""

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from mensarium import __version__

log = logging.getLogger(__name__)

PROTOCOL_VERSION = "2025-06-18"
OUTPUT_LIMIT = 20000
NAME_RE = re.compile(r"[^a-z0-9_]+")


class McpError(Exception):
    pass


class McpAuthError(McpError):
    """The server rejected the credentials (HTTP 401): a fresh token may help."""


@dataclass
class McpServer:
    """A server definition after config placeholders were filled."""

    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None


def tool_key(name: str) -> str:
    """MCP tool names become a lowercase segment of `mcp.<server>.<tool>`."""
    return NAME_RE.sub("_", name.lower()).strip("_")[:40] or "tool"


def check_arguments(args: Any, schema: dict[str, Any]) -> str | None:
    """A light check of the arguments against the tool's input schema: an object with the required keys."""
    if not isinstance(args, dict):
        return "arguments must be a JSON object"
    missing = [k for k in schema.get("required", []) if k not in args]
    if missing:
        return f"missing required arguments {missing}"
    props = schema.get("properties") or {}
    kinds: dict[str, type | tuple[type, ...]] = {
        "string": str, "integer": int, "number": (int, float), "boolean": bool, "array": list, "object": dict,
    }
    for key, value in args.items():
        expected = kinds.get((props.get(key) or {}).get("type", ""))
        if expected and value is not None and not isinstance(value, expected):
            return f"argument {key!r} must be {props[key]['type']}"
    return None


def render_content(result: dict[str, Any]) -> tuple[str, bool]:
    parts: list[str] = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(str(item.get("text", "")))
        elif kind == "resource":
            res = item.get("resource") or {}
            parts.append(str(res.get("text") or f"[resource {res.get('uri', '')}]"))
        elif kind == "resource_link":
            parts.append(f"[link {item.get('uri', '')}]")
        else:
            parts.append(f"[{kind} content: {item.get('mimeType', '')}]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False, indent=1))
    text = "\n".join(parts) or "(empty result)"
    if len(text) > OUTPUT_LIMIT:
        text = text[:OUTPUT_LIMIT] + "\n...[truncated]"
    return text, bool(result.get("isError"))


class McpClient:
    def __init__(self, server: McpServer, timeout_s: float = 60) -> None:
        self.server = server
        self.timeout_s = timeout_s
        self.tools: list[dict[str, Any]] = []
        self._next_id = 0

    def _id(self) -> int:
        self._next_id += 1
        return self._next_id

    async def request(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        raise NotImplementedError

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        raise NotImplementedError

    async def start(self) -> list[dict[str, Any]]:
        await self.request(
            "initialize",
            {"protocolVersion": PROTOCOL_VERSION, "capabilities": {}, "clientInfo": {"name": "mensarium", "version": __version__}},
            timeout=max(self.timeout_s, 90),
        )
        await self.notify("notifications/initialized")
        self.tools = await self.list_tools()
        return self.tools

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor = None
        for _ in range(20):
            result = await self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools += result.get("tools", [])
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call(self, name: str, arguments: dict[str, Any], timeout: float | None = None) -> tuple[str, bool]:
        result = await self.request("tools/call", {"name": name, "arguments": arguments}, timeout=timeout)
        return render_content(result or {})

    async def close(self) -> None:
        pass


class StdioMcp(McpClient):
    """Runs the server as a child process and speaks newline-delimited JSON-RPC over its stdin and stdout."""

    def __init__(self, server: McpServer, timeout_s: float = 60, extra_path: list[str] | None = None) -> None:
        super().__init__(server, timeout_s)
        self.extra_path = extra_path or []
        self.proc: asyncio.subprocess.Process | None = None
        self.pending: dict[int, asyncio.Future[Any]] = {}
        self.stderr: deque[str] = deque(maxlen=20)
        self.reader: asyncio.Task[None] | None = None
        self.err_reader: asyncio.Task[None] | None = None

    async def _spawn(self) -> None:
        path = os.pathsep.join([*self.extra_path, os.environ.get("PATH", "/usr/bin:/bin")])
        program = shutil.which(self.server.command or "", path=path)
        if program is None:
            raise McpError(f"program {self.server.command!r} not found on PATH")
        env = {**os.environ, "PATH": path, **self.server.env}
        self.proc = await asyncio.create_subprocess_exec(
            program,
            *self.server.args,
            cwd=self.server.cwd or str(Path.home()),
            env=env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
            limit=16 * 1024 * 1024,
        )
        self.reader = asyncio.create_task(self._read())
        self.err_reader = asyncio.create_task(self._read_stderr())

    async def start(self) -> list[dict[str, Any]]:
        await self._spawn()
        try:
            return await super().start()
        except BaseException:
            await self.close()
            raise

    async def _read_stderr(self) -> None:
        assert self.proc and self.proc.stderr
        async for line in self.proc.stderr:
            self.stderr.append(line.decode(errors="replace").rstrip())

    async def _read(self) -> None:
        assert self.proc and self.proc.stdout
        async for raw in self.proc.stdout:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if "method" in msg and "id" in msg:
                await self._answer_server(msg)
                continue
            fut = self.pending.pop(msg.get("id"), None) if isinstance(msg.get("id"), int) else None
            if fut and not fut.done():
                if "error" in msg:
                    fut.set_exception(McpError(str(msg["error"].get("message", msg["error"]))))
                else:
                    fut.set_result(msg.get("result"))
        tail = " | ".join(self.stderr) or "no output"
        for fut in self.pending.values():
            if not fut.done():
                fut.set_exception(McpError(f"MCP server exited: {tail[-400:]}"))
        self.pending.clear()

    async def _answer_server(self, msg: dict[str, Any]) -> None:
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": msg["id"]}
        if msg["method"] == "ping":
            reply["result"] = {}
        else:
            reply["error"] = {"code": -32601, "message": "not supported by this client"}
        await self._write(reply)

    async def _write(self, msg: dict[str, Any]) -> None:
        if not self.proc or not self.proc.stdin or self.proc.returncode is not None:
            raise McpError("MCP server is not running")
        self.proc.stdin.write((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        await self.proc.stdin.drain()

    async def request(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        rid = self._id()
        fut: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        self.pending[rid] = fut
        await self._write({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}})
        try:
            return await asyncio.wait_for(fut, timeout or self.timeout_s)
        except TimeoutError as e:
            raise McpError(f"{method} timed out") from e
        finally:
            self.pending.pop(rid, None)

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def close(self) -> None:
        for task in (self.reader, self.err_reader):
            if task:
                task.cancel()
        if self.proc and self.proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                self.proc.terminate()
            try:
                await asyncio.wait_for(self.proc.wait(), 5)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    self.proc.kill()


class HttpMcp(McpClient):
    """Streamable HTTP transport: JSON-RPC POSTs answered with JSON or a short SSE stream."""

    def __init__(self, server: McpServer, timeout_s: float = 60) -> None:
        super().__init__(server, timeout_s)
        self.session: str | None = None
        self.version: str | None = None
        self.client = httpx.AsyncClient(timeout=timeout_s, follow_redirects=True)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json", **self.server.headers}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.version:
            headers["MCP-Protocol-Version"] = self.version
        return headers

    async def _post(self, msg: dict[str, Any], timeout: float | None) -> httpx.Response:
        try:
            resp = await self.client.post(str(self.server.url), json=msg, headers=self._headers(), timeout=timeout or self.timeout_s)
        except httpx.HTTPError as e:
            raise McpError(f"cannot reach {self.server.url}: {e}") from e
        if resp.status_code == 401:
            raise McpAuthError(f"HTTP 401: {resp.text[:300]}")
        if resp.status_code >= 400:
            raise McpError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        if sid := resp.headers.get("mcp-session-id"):
            self.session = sid
        return resp

    async def request(self, method: str, params: dict[str, Any] | None = None, timeout: float | None = None) -> Any:
        rid = self._id()
        resp = await self._post({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}, timeout)
        if "text/event-stream" in resp.headers.get("content-type", ""):
            messages = [json.loads(line[5:]) for line in resp.text.splitlines() if line.startswith("data:") and line[5:].strip()]
        else:
            messages = [resp.json()] if resp.content else []
        for msg in messages:
            if isinstance(msg, dict) and msg.get("id") == rid:
                if "error" in msg:
                    raise McpError(str(msg["error"].get("message", msg["error"])))
                if method == "initialize":
                    self.version = (msg.get("result") or {}).get("protocolVersion")
                return msg.get("result")
        raise McpError(f"no answer to {method}")

    async def notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._post({"jsonrpc": "2.0", "method": method, "params": params or {}}, None)

    async def close(self) -> None:
        if self.session:
            with contextlib.suppress(httpx.HTTPError):
                await self.client.delete(str(self.server.url), headers=self._headers(), timeout=5)
        await self.client.aclose()


def connect(server: McpServer, extra_path: list[str] | None = None) -> McpClient:
    if server.transport == "http":
        return HttpMcp(server)
    return StdioMcp(server, extra_path=extra_path)


def describe(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What is kept of each tool: name, description, input schema and the hints that can raise the risk."""
    return [
        {
            "name": t.get("name", ""),
            "description": str(t.get("description") or "")[:1500],
            "input_schema": t.get("inputSchema") or {"type": "object", "properties": {}},
            "annotations": {k: v for k, v in (t.get("annotations") or {}).items() if k in ("destructiveHint", "openWorldHint")},
        }
        for t in tools
        if t.get("name")
    ]
