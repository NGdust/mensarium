"""LLM providers that run a local command-line agent (Claude Code, Codex CLI) as a one-shot model call.

The agent's own tools are switched off or sandboxed; our tools are described in the prompt and the answer is
forced into a JSON object by the CLI's schema option, then turned into a native tool call."""

import asyncio
import json
import logging
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
    CLAUDE_PROBE_MODEL,
    CODEX_MODELS,
    codex_config_model,
    codex_models,
    codex_rpc,
)
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import now_iso

log = logging.getLogger(__name__)

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


def _content_text(content: str | list[dict[str, Any]] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    parts = []
    for part in content:
        if part.get("type") == "text":
            parts.append(str(part.get("text", "")))
        elif part.get("type") == "image_url":
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
    for m in messages:
        if m.role == "user":
            out.append(f"### User\n{_content_text(m.content)}")
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


def extract_json_object(text: str) -> dict[str, Any] | None:
    """The first {...} object in the text that has a `type` field; code fences and prose around it are ignored."""
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start : i + 1])
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict) and "type" in obj:
                        return obj
                    break
        start = text.find("{", start + 1)
    return None


def parse_answer(obj: dict[str, Any]) -> ModelResponse:
    kind = obj.get("type")
    if kind == "tool_call" and obj.get("tool"):
        raw = obj.get("arguments") or "{}"
        args: dict[str, Any] | None = None
        err = None
        if isinstance(raw, dict):
            args, raw = raw, json.dumps(raw, ensure_ascii=False)
        else:
            try:
                parsed = json.loads(raw or "{}")
                args = parsed if isinstance(parsed, dict) else None
                err = None if args is not None else "arguments must be a JSON object"
            except json.JSONDecodeError as e:
                err = str(e)
        call = ProposedToolCall(id=new_id("call"), name=str(obj["tool"]), arguments=args, raw_arguments=str(raw), parse_error=err)
        return ModelResponse(text=str(obj.get("text") or "") or None, tool_calls=[call], finish_reason="tool_calls")
    return ModelResponse(text=str(obj.get("text") or ""), tool_calls=[], finish_reason="stop")


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

    @property
    def base_url(self) -> str:
        return self.command

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

    async def _exec(self, args: list[str], stdin: str, timeout_s: int, env: dict[str, str] | None = None) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            self.command, *args, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            cwd=self.workdir(), env={**os.environ, **(env or {})},
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(stdin.encode()), timeout_s)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise LLMError(f"{self.title} did not answer within {timeout_s}s") from None
        return proc.returncode or 0, out.decode(errors="replace"), err.decode(errors="replace")

    async def chat(self, request: ChatRequest, *, tools: list[ToolDefinition], response_schema: dict[str, Any] | None = None) -> ModelResponse:
        system = request.system.rstrip() + "\n\n" + FORMAT_RULES + "\n" + render_tools(tools)
        prompt = render_transcript(request.messages) + "\n\n### Now answer with exactly one JSON object."
        timeout = max(request.timeout_s, self.timeout_s)
        attempt = 0
        while True:
            try:
                return await self._call(request.model or self.default_model, system, prompt, timeout)
            except LLMError as e:
                if attempt >= self.max_retries or "did not answer" in str(e):
                    raise
                log.warning("cli provider failed, retrying", extra={"provider": self.name, "error": str(e)})
                attempt += 1
                await asyncio.sleep(2 * attempt)

    async def _call(self, model: str, system: str, prompt: str, timeout_s: int) -> ModelResponse:
        raise NotImplementedError

    async def fetch_limits(self) -> list[LimitWindow] | None:
        """Ask the CLI for its usage windows without a model call; None when the CLI has no such source."""
        return None

    def _set_limits(self, windows: list[LimitWindow], source: str) -> None:
        self.limits, self.limits_at, self.limits_source = windows, now_iso(), source

    async def aclose(self) -> None:
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

    async def _call(self, model: str, system: str, prompt: str, timeout_s: int) -> ModelResponse:
        # No --json-schema: it registers a tool, and with any tool present the model starts calling our action names
        # as functions. With no tools at all it can only write text, which holds the JSON object.
        # stream-json (not json) because the stream carries `rate_limit_event` with the subscription windows.
        args = [
            "-p", "--output-format", "stream-json", "--verbose", "--no-session-persistence", "--tools", "", "--setting-sources", "",
            "--strict-mcp-config", "--max-turns", "2", "--model", model, "--system-prompt", system,
        ]  # fmt: skip
        code, out, err = await self._exec(args, prompt, timeout_s)
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
        if not isinstance(answer, dict):
            answer = extract_json_object(str(data.get("result") or ""))
        resp = parse_answer(answer) if answer else ModelResponse(text=str(data.get("result") or ""), tool_calls=[], finish_reason="stop")
        usage = data.get("usage") or {}
        resp.usage = TokenUsage(
            prompt_tokens=int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0)),
            completion_tokens=int(usage.get("output_tokens", 0)),
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
        """A tiny haiku call: Claude Code only reports its windows alongside a real request."""
        await self._call(CLAUDE_PROBE_MODEL, "Answer with the single word: pong", "pong", 120)
        return self.limits


class CodexCliProvider(CliProvider):
    kind = "codex_cli"
    title = "Codex CLI"
    models = list(CODEX_MODELS)

    def __init__(self, name: str, command: str, default_model: str, timeout_s: int = 180, max_retries: int = 1) -> None:
        super().__init__(name, command, default_model or codex_config_model() or CODEX_MODELS[0], timeout_s, max_retries)
        self.models = list(CODEX_MODELS)

    async def list_models(self) -> list[ModelInfo]:
        self.models = await asyncio.to_thread(codex_models, self.command)
        return [ModelInfo(id=m) for m in self.models]

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

    async def _call(self, model: str, system: str, prompt: str, timeout_s: int) -> ModelResponse:
        workdir = Path(self.workdir())
        schema_file = workdir / "answer-schema.json"
        schema_file.write_text(json.dumps(ANSWER_SCHEMA))
        last = workdir / f"last-{new_id('msg')}.txt"
        args = [
            "exec", "--json", "--ephemeral", "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules", "--color", "never",
            "-s", "read-only", "-C", str(workdir), "-m", model, "--output-last-message", str(last),
            "--output-schema", str(schema_file), "-",
        ]  # fmt: skip
        full_prompt = "## System instructions\n" + system + "\n\n## Conversation\n" + prompt
        code, out, err = await self._exec(args, full_prompt, timeout_s)
        usage: dict[str, Any] = {}
        failure = ""
        for line in out.splitlines():
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "turn.completed":
                usage = ev.get("usage") or {}
            elif ev.get("type") in ("turn.failed", "error"):
                failure = str((ev.get("error") or {}).get("message") or ev.get("message") or "")
        try:
            text = last.read_text().strip()
        except OSError:
            text = ""
        finally:
            last.unlink(missing_ok=True)
        if not text:
            raise LLMError(f"codex returned no answer (exit {code}): {(failure or err or out)[-400:]}")
        try:
            answer = json.loads(text)
        except json.JSONDecodeError as e:
            raise LLMError(f"codex answered without the JSON object: {text[:400]}") from e
        resp = parse_answer(answer)
        resp.usage = TokenUsage(prompt_tokens=int(usage.get("input_tokens", 0)), completion_tokens=int(usage.get("output_tokens", 0)))
        resp.raw_provider_response = {"usage": usage}
        return resp
