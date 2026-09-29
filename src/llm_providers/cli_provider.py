"""LLM providers that run a local command-line agent (Claude Code, Codex CLI) as a model call.

The agent's own tools are switched off or sandboxed; our tools are described in the prompt and the answer is
forced into a JSON object by the CLI's schema option, then turned into a native tool call. A task keeps one CLI
session: each step resumes it with only the messages it has not seen, so the CLI serves the rest from its cache."""

import asyncio
import base64
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from mensarium.contracts.limits import LimitWindow
from mensarium.contracts.llm import (
    ChatRequest,
    Message,
    ModelInfo,
    ModelResponse,
    ProposedToolCall,
    ProviderHealth,
    TokenUsage,
    ToolDefinition,
)
from mensarium.llm_providers.base import LLMError
from mensarium.llm_providers.local_cli import (
    CLAUDE_MODELS,
    codex_context_windows,
    codex_models,
    codex_rpc,
)
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import now_iso
from mensarium.shared.toolargs import parse_tool_arguments

log = logging.getLogger(__name__)

MAX_SESSIONS = 32
STDOUT_LINE_LIMIT = 2**24
ANSWER_NOW = "\n\n### Now answer with exactly one JSON object."

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "type": {"type": "string", "enum": ["tool_call", "final"]},
        "tool": {"type": "string"},
        "arguments": {"type": "string"},
        "text": {"type": "string"},
    },
    "required": ["type", "tool", "arguments", "text"],
    "additionalProperties": False,
}
FORMAT_RULES = (
    "## How to answer\n"
    "You are the reasoning engine of Mensarium. You have NO functions or tools of your own in this session: do not try to "
    "call any function, and do not look at this machine. The actions listed under 'Actions you can request' run on the "
    "user's device only after you request one, and their output comes back to you in the next message.\n"
    "Every answer is exactly one JSON object with the fields type, tool, arguments, text:\n"
    '- to request an action: {"type": "tool_call", "tool": "<action name>", "arguments": "<its arguments as a JSON object encoded in a string>", "text": "<one short sentence on why>"}\n'
    '- when the task is done or you need the user: {"type": "final", "tool": "", "arguments": "", "text": "<the answer for the user>"}\n'
    "Request one action per answer and wait for its result.\n"
)


Image = tuple[str, str]  # (media type, base64 data)


def _image(part: dict[str, Any]) -> Image | None:
    url = str((part.get("image_url") or {}).get("url") or "")
    if not url.startswith("data:") or ";base64," not in url:
        return None
    media, data = url[5:].split(";base64,", 1)
    return media or "image/png", data


def collect_images(messages: list[Message]) -> list[Image]:
    """Pictures in the messages, in transcript order; the transcript refers to them as [image N]."""
    out: list[Image] = []
    for m in messages:
        if isinstance(m.content, list):
            out += [img for part in m.content if part.get("type") == "image_url" and (img := _image(part))]
    return out


def _content_text(content: str | list[dict[str, Any]] | None, counter: list[int] | None = None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if part.get("type") == "text":
            parts.append(str(part.get("text", "")))
        elif part.get("type") == "image_url":
            if counter is not None and _image(part):
                counter[0] += 1
                parts.append(f"[image {counter[0]}: attached to this request]")
            else:
                parts.append("[image omitted: this provider cannot see images]")
    return "\n".join(parts)


def render_tools(tools: list[ToolDefinition]) -> str:
    if not tools:
        return "## Actions you can request\n(none)\n"
    lines = ["## Actions you can request", "Name, description and the JSON schema of the arguments:"]
    for t in tools:
        lines.append(f"- {t.name}: {t.description}\n  arguments schema: {json.dumps(t.parameters, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def render_transcript(messages: list[Message]) -> str:
    out = []
    counter = [0]
    for m in messages:
        if m.role == "user":
            out.append(f"### User\n{_content_text(m.content, counter)}")
        elif m.role == "assistant":
            calls = m.tool_calls or []
            if calls:
                for tc in calls:
                    args = tc.get("arguments")
                    args_s = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
                    out.append(f"### Assistant (tool call {tc.get('id', '')})\n" + json.dumps({"type": "tool_call", "tool": tc.get("name"), "arguments": args_s, "text": _content_text(m.content)}, ensure_ascii=False))
            else:
                out.append(f"### Assistant\n{_content_text(m.content)}")
        elif m.role == "tool":
            out.append(f"### Tool result ({m.tool_call_id or ''})\n{_content_text(m.content)}")
        elif m.role == "system":
            out.append(f"### System\n{_content_text(m.content)}")
    return "\n\n".join(out)


_DECODER = json.JSONDecoder()


def json_objects(text: str) -> list[dict[str, Any]]:
    """The top-level {...} objects in the text that have a `type` field; code fences and prose around them are ignored."""
    found = []
    start = text.find("{")
    while start != -1:
        try:
            obj, end = _DECODER.raw_decode(text, start)
        except json.JSONDecodeError:
            obj = None
        if isinstance(obj, dict) and "type" in obj:
            found.append(obj)
            start = text.find("{", end)
        else:
            start = text.find("{", start + 1)
    return found


_TEXT_FIELD = re.compile(r'"text"\s*:\s*"')


def partial_json_string(body: str) -> str:
    """The value of a JSON string from the text after its opening quote, which may be cut off anywhere."""
    escaped = False
    for i, ch in enumerate(body):
        if escaped:
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            body = body[:i]
            break
    for cut in range(len(body), max(len(body) - 12, 0) - 1, -1):  # an escape cut short, like \u04 or half a surrogate pair
        try:
            text = str(json.loads(f'"{body[:cut]}"', strict=False))
        except json.JSONDecodeError:
            continue
        if not text or not "\ud800" <= text[-1] <= "\udbff":
            return text
    return ""


class AnswerStream:
    """Hands on the `text` field of the answer object while the CLI is still writing it."""

    def __init__(self, on_text: Callable[[str], None]) -> None:
        self.on_text = on_text
        self.raw = ""
        self.sent = 0

    def feed(self, chunk: str) -> None:
        self.raw += chunk
        if not (m := _TEXT_FIELD.search(self.raw)):
            return
        text = partial_json_string(self.raw[m.end() :])
        if len(text) > self.sent:
            self.on_text(text[self.sent :])
            self.sent = len(text)


async def _communicate(proc: asyncio.subprocess.Process, data: bytes, on_line: Callable[[str], None] | None) -> tuple[bytes, bytes]:
    """proc.communicate() that also hands on each stdout line as it arrives."""
    if on_line is None:
        return await proc.communicate(data)
    assert proc.stdin and proc.stdout and proc.stderr
    stdin, stdout = proc.stdin, proc.stdout

    async def feed() -> None:
        with contextlib.suppress(BrokenPipeError, ConnectionResetError):
            stdin.write(data)
            await stdin.drain()
            stdin.close()

    async def read() -> bytes:
        lines = []
        async for line in stdout:
            lines.append(line)
            on_line(line.decode(errors="replace"))
        return b"".join(lines)

    _, out, err = await asyncio.gather(feed(), read(), proc.stderr.read())
    await proc.wait()
    return out, err


def parse_answer(obj: dict[str, Any]) -> ModelResponse:
    kind = obj.get("type")
    if kind == "tool_call" and obj.get("tool"):
        args, raw, err = parse_tool_arguments(obj.get("arguments") or "{}")
        call = ProposedToolCall(id=new_id("call"), name=str(obj["tool"]), arguments=args, raw_arguments=raw, parse_error=err)
        return ModelResponse(text=str(obj.get("text") or "") or None, tool_calls=[call], finish_reason="tool_calls")
    return ModelResponse(text=str(obj.get("text") or ""), tool_calls=[], finish_reason="stop")


_TOOL_CALL = re.compile(r'"type"\s*:\s*"tool_call"')
_TOOL_NAME = re.compile(r'"tool"\s*:\s*"([\w.-]+)"')
_ACTION_NAME = re.compile(r"[a-z_]+\.[\w.-]+")


def _loose_tool_call(obj: dict[str, Any]) -> dict[str, Any] | None:
    """A tool call written with a wrong `type`, e.g. {"type": "files.edit", "tool": "files.edit", ...}."""
    tool = obj.get("tool") or obj.get("type")
    if obj.get("type") == "final" or not isinstance(tool, str) or not _ACTION_NAME.fullmatch(tool):
        return None
    return {**obj, "type": "tool_call", "tool": tool}


def parse_text_answer(text: str) -> ModelResponse:
    # Models sometimes write a stray object before the real one: take the first proper action, then a tool call
    # with a wrong type, and never let an object that is neither end the task as an empty final answer.
    objects = json_objects(text)
    if obj := next((o for o in objects if (o["type"] == "tool_call" and o.get("tool")) or o["type"] == "final"), None):
        return parse_answer(obj)
    if obj := next(filter(None, map(_loose_tool_call, objects)), None):
        return parse_answer(obj)
    if _TOOL_CALL.search(text):
        # A tool call written as broken JSON must not end the task: the model gets the error back and repeats the call.
        name = m.group(1) if (m := _TOOL_NAME.search(text)) else "unknown"
        err = "the answer is not one valid JSON object, send the action again with correctly escaped arguments"
        call = ProposedToolCall(id=new_id("call"), name=name, arguments=None, raw_arguments=text, parse_error=err)
        return ModelResponse(text=None, tool_calls=[call], finish_reason="tool_calls")
    if objects:
        said = next((o["text"] for o in objects if isinstance(o.get("text"), str) and o["text"].strip()), "")
        return ModelResponse(text=said, tool_calls=[], finish_reason="stop")
    return ModelResponse(text=text, tool_calls=[], finish_reason="stop")


@dataclass
class CliSession:
    """A CLI conversation holding the first len(sent) request messages and its answer to them."""

    id: str
    model: str
    system: str
    sent: list[str]
    answer_call: str | None


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class CliProvider:
    kind = ""
    title = ""
    models: list[str] = []

    def __init__(self, name: str, command: str, default_model: str, timeout_s: int = 180, max_retries: int = 1) -> None:
        self.name = name
        self.command = command
        self.default_model = default_model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.vision_model: str | None = None
        self.limits: list[LimitWindow] | None = None
        self.limits_at: str | None = None
        self.limits_source = ""
        self._workdir: str | None = None
        self.sessions: OrderedDict[str, CliSession] = OrderedDict()
        self.windows: dict[str, int] = {}

    @property
    def base_url(self) -> str:
        return self.command

    async def context_window(self, model: str) -> int | None:
        return self.windows.get(model or self.default_model)

    def workdir(self) -> str:
        """An empty directory the agent runs in, so it sees nothing of the Core host even if it looks around."""
        if self._workdir is None or not os.path.isdir(self._workdir):
            self._workdir = tempfile.mkdtemp(prefix="mensarium-cli-")
        return self._workdir

    async def list_models(self) -> list[ModelInfo]:
        return [ModelInfo(id=m) for m in self.models]

    async def healthcheck(self) -> ProviderHealth:
        if not (shutil.which(self.command) or os.access(self.command, os.X_OK)):
            return ProviderHealth(ok=False, detail=f"{self.command} not found")
        ok, detail = await asyncio.to_thread(self.login_status)
        return ProviderHealth(ok=ok, detail=detail)

    def login_status(self) -> tuple[bool, str]:
        raise NotImplementedError

    async def _exec(
        self, args: list[str], stdin: str, timeout_s: int, env: dict[str, str] | None = None, on_line: Callable[[str], None] | None = None
    ) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            self.command, *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=self.workdir(), env={**os.environ, **(env or {})}, limit=STDOUT_LINE_LIMIT,
        )
        try:
            out, err = await asyncio.wait_for(_communicate(proc, stdin.encode(), on_line), timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise LLMError(f"{self.title} did not answer within {timeout_s}s") from None
        except BaseException:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            raise
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    async def chat(
        self,
        request: ChatRequest,
        *,
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ModelResponse:
        system = request.system.rstrip() + "\n\n" + FORMAT_RULES + "\n" + render_tools(tools)
        model = request.model or self.default_model
        key = request.metadata.get("task_id")
        timeout = max(request.timeout_s, self.timeout_s)
        attempt, streamed = 0, False

        def text(piece: str) -> None:
            nonlocal streamed
            streamed = True
            if on_text:
                on_text(piece)

        while True:
            session, unseen = self._continuation(key, model, system, request.messages)
            prompt = render_transcript(unseen) + ANSWER_NOW
            try:
                resp = await self._call(
                    model, system, prompt, timeout, resume=session.id if session else None, persist=bool(key),
                    on_text=text if on_text and not streamed else None, images=collect_images(unseen),
                )  # fmt: skip
            except LLMError as e:
                if session:
                    self._discard(session.id)
                if attempt >= self.max_retries or "did not answer" in str(e):
                    raise
                log.warning("cli provider failed, retrying", extra={"provider": self.name, "error": str(e)})
                attempt += 1
                await asyncio.sleep(2 * attempt)
                continue
            sid = resp.raw_provider_response.get("session_id")
            if key and isinstance(sid, str) and sid:
                if session and session.id != sid:
                    self._discard(session.id)
                sent = [_digest(m.model_dump_json()) for m in request.messages]
                self._keep(key, CliSession(sid, model, _digest(system), sent, resp.tool_calls[0].id if resp.tool_calls else None))
            return resp

    def _continuation(self, key: str | None, model: str, system: str, messages: list[Message]) -> tuple[CliSession | None, list[Message]]:
        """The task's session if this request extends what it holds by its answer and new messages, with those messages.

        The session is taken out while the call runs, so a failed or cancelled call never leaves a stale one."""
        s = self.sessions.pop(key, None) if key else None
        if s is None:
            return None, messages
        n = len(s.sent)
        answer = messages[n] if len(messages) > n else None
        calls = (answer.tool_calls or []) if answer else []
        if (
            answer is None
            or answer.role != "assistant"
            or (calls[0].get("id") if calls else None) != s.answer_call
            or (s.model, s.system) != (model, _digest(system))
            or [_digest(m.model_dump_json()) for m in messages[:n]] != s.sent
        ):
            self._discard(s.id)
            return None, messages
        return s, messages[n + 1 :]

    def _keep(self, key: str, session: CliSession) -> None:
        self.sessions[key] = session
        while len(self.sessions) > MAX_SESSIONS:
            _, old = self.sessions.popitem(last=False)
            self._discard(old.id)

    def _discard(self, session_id: str) -> None:
        for path in self._session_files(session_id):
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)

    def _session_files(self, session_id: str) -> list[Path]:
        return []

    async def _call(
        self, model: str, system: str, prompt: str, timeout_s: int, resume: str | None = None, persist: bool = False,
        on_text: Callable[[str], None] | None = None, images: list[Image] | None = None,
    ) -> ModelResponse:
        """One CLI run. `resume` continues that session with `prompt`; `persist` keeps a new session for resuming;
        `on_text` gets the answer text as it is written, when the CLI can stream it; `images` go with the prompt."""
        raise NotImplementedError

    async def fetch_limits(self) -> list[LimitWindow] | None:
        """Ask the CLI for its usage windows without a model call; None when the CLI has no such source."""
        return None

    def _set_limits(self, windows: list[LimitWindow], source: str) -> None:
        self.limits, self.limits_at, self.limits_source = windows, now_iso(), source

    async def aclose(self) -> None:
        while self.sessions:
            self._discard(self.sessions.popitem()[1].id)
        if self._workdir:
            shutil.rmtree(self._workdir, ignore_errors=True)
            self._workdir = None


class ClaudeCodeProvider(CliProvider):
    kind = "claude_code"
    title = "Claude Code"
    models = list(CLAUDE_MODELS)

    def login_status(self) -> tuple[bool, str]:
        import subprocess

        try:
            r = subprocess.run([self.command, "auth", "status"], capture_output=True, text=True, timeout=15)
            out = r.stdout + r.stderr
            status = json.loads(out[out.index("{") :]) if "{" in out else {}
        except (OSError, subprocess.TimeoutExpired, ValueError, json.JSONDecodeError) as e:
            return False, f"cannot check login: {e}"
        if status.get("loggedIn"):
            return True, f"logged in ({status.get('email') or status.get('authMethod') or 'ok'})"
        return False, "not logged in: run `claude` on the Core host and log in"

    def _session_files(self, session_id: str) -> list[Path]:
        config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        return [*config_dir.glob(f"projects/*/{session_id}.jsonl"), *config_dir.glob(f"projects/*/{session_id}")]

    async def aclose(self) -> None:
        workdir = self._workdir
        await super().aclose()
        if workdir:
            config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
            shutil.rmtree(config_dir / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.realpath(workdir)), ignore_errors=True)

    async def _call(
        self, model: str, system: str, prompt: str, timeout_s: int, resume: str | None = None, persist: bool = False,
        on_text: Callable[[str], None] | None = None, images: list[Image] | None = None,
    ) -> ModelResponse:
        # No --json-schema: it registers a tool, and with any tool present the model starts calling our action names
        # as functions. With no tools at all it can only write text, which holds the JSON object.
        # stream-json (not json) because the stream carries `rate_limit_event` with the subscription windows.
        # The system prompt goes through a file: with tool schemas rendered into it, it outgrows the 128 KiB
        # a single command-line argument may hold on Linux (E2BIG).
        fd, path = tempfile.mkstemp(prefix="mensarium-system-", suffix=".md", dir=self.workdir())
        os.close(fd)
        system_file = Path(path)
        system_file.write_text(system)
        args = [
            "-p", "--output-format", "stream-json", "--verbose", "--tools", "", "--setting-sources", "",
            "--strict-mcp-config", "--max-turns", "2", "--model", model, "--system-prompt-file", str(system_file),
        ]  # fmt: skip
        if on_text:
            args.append("--include-partial-messages")
        if images:
            # Pictures travel only as content blocks of a stream-json user message.
            args += ["--input-format", "stream-json"]
            content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
            content += [{"type": "image", "source": {"type": "base64", "media_type": media, "data": data}} for media, data in images]
            prompt = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
        new_session = None if resume or not persist else str(uuid.uuid4())
        if resume:
            args += ["--resume", resume]
        elif new_session:
            args += ["--session-id", new_session]
        else:
            args.append("--no-session-persistence")
        try:
            resp = await self._run_claude(args, prompt, timeout_s, on_text)
        except LLMError:
            if new_session:
                self._discard(new_session)
            raise
        finally:
            system_file.unlink(missing_ok=True)
        usage = resp.raw_provider_response.get("modelUsage") or {}
        if window := max((int(u.get("contextWindow") or 0) for u in usage.values() if isinstance(u, dict)), default=0):
            self.windows[model] = window
        return resp

    async def _run_claude(self, args: list[str], prompt: str, timeout_s: int, on_text: Callable[[str], None] | None = None) -> ModelResponse:
        stream = AnswerStream(on_text) if on_text else None

        def on_line(line: str) -> None:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                return
            delta = (ev.get("event") or {}).get("delta") or {} if ev.get("type") == "stream_event" else {}
            if stream and delta.get("type") == "text_delta":
                stream.feed(str(delta.get("text") or ""))

        code, out, err = await self._exec(args, prompt, timeout_s, on_line=on_line if stream else None)
        data: dict[str, Any] = {}
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "result":
                data = ev
            elif ev.get("type") == "rate_limit_event":
                self._note_rate_limits(ev.get("rate_limit_info") or {})
        if not data:
            raise LLMError(f"claude returned no result (exit {code}): {(err or out)[-400:]}")
        if data.get("is_error"):
            raise LLMError(f"claude error: {str(data.get('result'))[:400]}")
        answer = data.get("structured_output")
        resp = parse_answer(answer) if isinstance(answer, dict) else parse_text_answer(str(data.get("result") or ""))
        usage = data.get("usage") or {}
        read, written = int(usage.get("cache_read_input_tokens") or 0), int(usage.get("cache_creation_input_tokens") or 0)
        resp.usage = TokenUsage(
            prompt_tokens=int(usage.get("input_tokens") or 0) + read + written,
            completion_tokens=int(usage.get("output_tokens") or 0),
            cached_tokens=read,
            cache_write_tokens=written,
        )
        resp.raw_provider_response = {k: data.get(k) for k in ("session_id", "num_turns", "total_cost_usd", "modelUsage")}
        return resp


    def _note_rate_limits(self, info: dict[str, Any]) -> None:
        windows = []
        labels = {"five_hour": "5 hours", "seven_day": "7 days"}
        for key, w in (info.get("unifiedWindows") or {}).items():
            if not isinstance(w, dict) or w.get("utilization") is None:
                continue
            reset = w.get("resetsAt")
            windows.append(LimitWindow(
                label=labels.get(key, key), used_percent=round(float(w["utilization"]) * 100, 1),
                resets_at=datetime.fromtimestamp(int(reset), tz=UTC).isoformat() if reset else None,
            ))
        if windows:
            self._set_limits(windows, "claude rate_limit_event")

    async def fetch_limits(self) -> list[LimitWindow] | None:
        """Read subscription usage without generating tokens, even when quota is exhausted."""
        config_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
        try:
            raw = await asyncio.to_thread((config_dir / ".credentials.json").read_text)
            credentials = json.loads(raw)
            oauth = credentials.get("claudeAiOauth") if isinstance(credentials, dict) else None
            token = oauth.get("accessToken") if isinstance(oauth, dict) else None
        except (OSError, ValueError):
            raise LLMError("Cannot read Claude OAuth credentials for usage polling; log in with `claude` on the Core host.") from None
        if not isinstance(token, str) or not token.strip():
            raise LLMError("Claude usage polling requires subscription OAuth credentials; log in with `claude` on the Core host.")
        try:
            async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
                response = await client.get(
                    "https://api.anthropic.com/api/oauth/usage",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "anthropic-beta": "oauth-2025-04-20",
                        "Accept": "application/json",
                    },
                )
        except httpx.HTTPError:
            raise LLMError("Claude usage request failed: network error or timeout.") from None
        if response.status_code in (401, 403):
            raise LLMError("Claude usage authorization failed; renew login with `claude` on the Core host.")
        if response.status_code != 200:
            raise LLMError(f"Claude usage request failed (HTTP {response.status_code}).")
        try:
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError
            labels = {"five_hour": "5 hours", "seven_day": "7 days"}
            windows = []
            for key, value in data.items():
                if key == "extra_usage" or not isinstance(value, dict) or value.get("utilization") is None:
                    continue
                utilization = value["utilization"]
                if isinstance(utilization, bool) or not isinstance(utilization, (int, float)):
                    raise ValueError
                if not 0 <= utilization < float("inf"):
                    raise ValueError
                reset = value.get("resets_at")
                if reset is not None and not isinstance(reset, str):
                    raise ValueError
                windows.append(LimitWindow(
                    label=labels.get(str(key), str(key)),
                    used_percent=round(utilization, 1),
                    resets_at=reset,
                ))
            if not windows:
                raise ValueError
        except (ValueError, TypeError):
            raise LLMError("Claude usage API returned an invalid or empty usage response.") from None
        self._set_limits(windows, "claude OAuth usage")
        return self.limits


class CodexCliProvider(CliProvider):
    kind = "codex_cli"
    title = "Codex CLI"
    models: list[str] = []

    def __init__(self, name: str, command: str, default_model: str, timeout_s: int = 180, max_retries: int = 1) -> None:
        super().__init__(name, command, default_model, timeout_s, max_retries)
        self.models = []

    async def list_models(self) -> list[ModelInfo]:
        try:
            self.models = await asyncio.to_thread(codex_models, self.command)
        except (OSError, RuntimeError) as e:
            raise LLMError(f"cannot discover Codex models: {e}") from e
        return [ModelInfo(id=m) for m in self.models]

    async def context_window(self, model: str) -> int | None:
        model = model or self.default_model or (self.models[0] if self.models else "")
        if model not in self.windows:
            self.windows.update(await asyncio.to_thread(codex_context_windows))
        return self.windows.get(model)

    def login_status(self) -> tuple[bool, str]:
        import subprocess

        try:
            r = subprocess.run([self.command, "login", "status"], capture_output=True, text=True, timeout=15)
        except (OSError, subprocess.TimeoutExpired) as e:
            return False, f"cannot check login: {e}"
        out = (r.stdout + r.stderr).strip()
        if r.returncode == 0 and "logged in" in out.lower():
            return True, out.splitlines()[0]
        return False, "not logged in: run `codex login` on the Core host"

    async def fetch_limits(self) -> list[LimitWindow] | None:
        """`codex app-server` over stdio: account/rateLimits/read; no model call, no quota spent."""
        try:
            result = await asyncio.to_thread(codex_rpc, self.command, "account/rateLimits/read", None, self.workdir())
        except (OSError, RuntimeError) as e:
            raise LLMError(f"codex rate limits: {e}") from e
        snap = result.get("rateLimits") or {}
        windows = []
        for w in (snap.get("primary"), snap.get("secondary")):
            if not isinstance(w, dict) or w.get("usedPercent") is None:
                continue
            mins = w.get("windowDurationMins") or 0
            label = "7 days" if mins >= 10080 else f"{mins // 60} hours" if mins >= 60 else f"{mins} min" if mins else "window"
            reset = w.get("resetsAt")
            windows.append(LimitWindow(
                label=label, used_percent=float(w["usedPercent"]),
                resets_at=datetime.fromtimestamp(int(reset), tz=UTC).isoformat() if reset else None,
                detail=str(snap.get("planType") or ""),
            ))
        self._set_limits(windows, "codex app-server")
        return windows

    async def _call(
        self, model: str, system: str, prompt: str, timeout_s: int, resume: str | None = None, persist: bool = False,
        on_text: Callable[[str], None] | None = None, images: list[Image] | None = None,
    ) -> ModelResponse:
        """`codex exec --json` reports whole items only, so the answer is not streamed; pictures go as `--image` files."""
        if not self.models or model not in self.models:
            await self.list_models()
        if not model:
            model = self.models[0]
        if model not in self.models:
            raise LLMError(
                f"Codex model '{model}' is unavailable for this account. "
                f"Select an available model in Settings -> Providers or the chat: {', '.join(self.models)}"
            )
        workdir = Path(self.workdir())
        schema_file = workdir / "answer-schema.json"
        schema_file.write_text(json.dumps(ANSWER_SCHEMA))
        last = workdir / f"last-{new_id('msg')}.txt"
        pictures = []
        for media, data in images or []:
            path = workdir / f"img-{new_id('img')}.{media.rsplit('/', 1)[-1].replace('jpeg', 'jpg')}"
            try:
                path.write_bytes(base64.b64decode(data))
            except (ValueError, TypeError):
                continue
            pictures += ["--image", str(path)]
        common = [
            "--json", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules", "-m", model,
            "--output-last-message", str(last), "--output-schema", str(schema_file), *pictures,
        ]  # fmt: skip
        if resume:
            args = ["exec", "resume", resume, *common, "-c", 'sandbox_mode="read-only"', "-"]
            stdin = prompt
        else:
            args = ["exec", *common, *([] if persist else ["--ephemeral"]), "--color", "never", "-s", "read-only", "-C", str(workdir), "-"]
            stdin = "## System instructions\n" + system + "\n\n## Conversation\n" + prompt
        try:
            code, out, err = await self._exec(args, stdin, timeout_s)
        finally:
            for item in pictures[1::2]:
                Path(item).unlink(missing_ok=True)
        usage: dict[str, Any] = {}
        failure = thread = ""
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "thread.started":
                thread = str(ev.get("thread_id") or "")
            elif ev.get("type") == "turn.completed":
                usage = ev.get("usage") or {}
            elif ev.get("type") in ("turn.failed", "error"):
                failure = str((ev.get("error") or {}).get("message") or ev.get("message") or "")
        try:
            text = last.read_text().strip()
        except OSError:
            text = ""
        finally:
            last.unlink(missing_ok=True)
        try:
            if not text:
                raise LLMError(f"codex returned no answer (exit {code}): {(failure or err or out)[-400:]}")
            try:
                answer = json.loads(text)
            except json.JSONDecodeError as e:
                raise LLMError(f"codex answered without the JSON object: {text[:400]}") from e
        except LLMError:
            if thread and not resume:
                self._discard(thread)
            raise
        resp = parse_answer(answer)
        resp.usage = TokenUsage(
            prompt_tokens=int(usage.get("input_tokens") or 0),
            completion_tokens=int(usage.get("output_tokens") or 0),
            cached_tokens=int(usage.get("cached_input_tokens") or 0),
        )
        resp.raw_provider_response = {"usage": usage, "session_id": thread or resume}
        return resp

    def _session_files(self, session_id: str) -> list[Path]:
        codex_home = Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")
        return list(codex_home.glob(f"sessions/*/*/*/rollout-*-{session_id}.jsonl"))
