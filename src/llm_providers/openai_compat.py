import asyncio
import json
import logging
from collections.abc import Callable
from datetime import timedelta
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
from mensarium.shared.timeutil import now_iso, utcnow
from mensarium.shared.toolargs import parse_tool_arguments

log = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


def _parse_duration(text: str) -> float | None:
    """OpenAI reset headers look like "1s", "6m0s", "1h2m3.5s"."""
    if not text:
        return None
    total, num = 0.0, ""
    for ch in text:
        if ch.isdigit() or ch == ".":
            num += ch
        elif ch in "hms" and num:
            total += float(num) * {"h": 3600, "m": 60, "s": 1}[ch]
            num = ""
        else:
            return None
    return total if not num else None


def wire_name(name: str) -> str:
    return name.replace(".", "__")


def domain_name(name: str) -> str:
    return name.replace("__", ".")


def _to_wire(m: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": m.role, "content": m.content if m.content is not None else ""}
    if m.tool_calls:
        out["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {"name": wire_name(tc["name"]), "arguments": tc["arguments"]},
            }
            for tc in m.tool_calls
        ]
    if m.tool_call_id:
        out["tool_call_id"] = m.tool_call_id
    return out


def _usage(usage: dict[str, Any], timings: dict[str, Any] | None) -> TokenUsage:
    """Cached input comes as prompt_tokens_details (OpenAI, OpenRouter) or llama.cpp's timings.cache_n."""
    details = usage.get("prompt_tokens_details") or {}
    return TokenUsage(
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        cached_tokens=int(details.get("cached_tokens") or (timings or {}).get("cache_n") or 0),
        cache_write_tokens=int(details.get("cache_write_tokens") or 0),
    )


async def _read_stream(resp: httpx.Response, on_text: Callable[[str], None]) -> dict[str, Any]:
    """Server-sent chunks of /chat/completions folded into one non-streamed response body."""
    content: list[str] = []
    calls: dict[int, dict[str, Any]] = {}
    out: dict[str, Any] = {}
    finish = None
    async for line in resp.aiter_lines():
        if not line.startswith("data:") or (chunk := line[5:].strip()) == "[DONE]":
            continue
        data = json.loads(chunk)
        if data.get("error"):
            raise LLMError(f"provider error: {str(data['error'])[:500]}")
        out |= {k: data[k] for k in ("usage", "timings") if data.get(k)}
        for choice in data.get("choices") or []:
            delta = choice.get("delta") or {}
            if piece := delta.get("content"):
                content.append(piece)
                on_text(piece)
            for tc in delta.get("tool_calls") or []:
                call = calls.setdefault(int(tc.get("index") or 0), {"id": None, "function": {"name": "", "arguments": ""}})
                fn = tc.get("function") or {}
                call["id"] = tc.get("id") or call["id"]
                call["function"]["name"] = fn.get("name") or call["function"]["name"]
                if isinstance(args := fn.get("arguments"), str):
                    call["function"]["arguments"] += args
                elif args:
                    call["function"]["arguments"] = args
            finish = choice.get("finish_reason") or finish
    message = {"content": "".join(content) or None, "tool_calls": [calls[i] for i in sorted(calls)]}
    return {"choices": [{"message": message, "finish_reason": finish}], **out}


class OpenAICompatibleProvider:
    """Ollama Cloud, local Ollama and llama.cpp all expose an OpenAI-compatible /v1 API."""

    def __init__(
        self,
        name: str,
        base_url: str,
        default_model: str,
        api_key: str | None = None,
        timeout_s: int = 90,
        max_retries: int = 2,
        vision_model: str | None = None,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.vision_model = vision_model
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._client = httpx.AsyncClient(base_url=self.base_url, headers=headers, timeout=timeout_s)
        self.limits: list[LimitWindow] | None = None
        self.limits_at: str | None = None
        self.limits_source = ""
        self._model_limits: dict[str, list[LimitWindow]] = {}

    async def _request(self, method: str, path: str, model: str | None = None, **kwargs: Any) -> dict[str, Any]:
        attempt = 0
        while True:
            try:
                resp = await self._client.request(method, path, **kwargs)
            except httpx.TransportError as e:
                if attempt >= self.max_retries:
                    raise LLMError(f"transport error: {e}") from e
            else:
                if model and "x-ratelimit-limit-tokens" in resp.headers:
                    self._note_headers(model, resp.headers)
                if resp.status_code < 400:
                    return resp.json()
                if resp.status_code not in RETRY_STATUS or attempt >= self.max_retries:
                    raise LLMError(f"HTTP {resp.status_code}: {resp.text[:500]}")
            attempt += 1
            await asyncio.sleep(min(2**attempt, 10))

    async def list_models(self) -> list[ModelInfo]:
        data = await self._request("GET", "/models")
        return [ModelInfo(id=m["id"]) for m in data.get("data", [])]

    async def healthcheck(self) -> ProviderHealth:
        try:
            models = await self.list_models()
        except LLMError as e:
            return ProviderHealth(ok=False, detail=str(e))
        return ProviderHealth(ok=True, detail=f"{len(models)} models available")

    async def chat(
        self,
        request: ChatRequest,
        *,
        tools: list[ToolDefinition],
        response_schema: dict[str, Any] | None = None,
        on_text: Callable[[str], None] | None = None,
    ) -> ModelResponse:
        body: dict[str, Any] = {
            "model": request.model,
            "messages": [{"role": "system", "content": request.system}]
            + [_to_wire(m) for m in request.messages],
            "temperature": request.temperature,
            "max_tokens": request.max_output_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = [
                {
                    "type": "function",
                    "function": {"name": wire_name(t.name), "description": t.description, "parameters": t.parameters},
                }
                for t in tools
            ]
        if response_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "out", "schema": response_schema}}
        if on_text:
            body |= {"stream": True, "stream_options": {"include_usage": True}}
            return self._parse(await self._stream(body, request.timeout_s, on_text))
        data = await self._request("POST", "/chat/completions", model=request.model, json=body, timeout=request.timeout_s)
        return self._parse(data)

    async def _stream(self, body: dict[str, Any], timeout_s: int, on_text: Callable[[str], None]) -> dict[str, Any]:
        """A streamed completion assembled into the shape of a plain one. Retried only until the first text arrived."""
        attempt, streamed = 0, False

        def text(piece: str) -> None:
            nonlocal streamed
            streamed = True
            on_text(piece)

        while True:
            try:
                async with self._client.stream("POST", "/chat/completions", json=body, timeout=timeout_s) as resp:
                    if "x-ratelimit-limit-tokens" in resp.headers:
                        self._note_headers(body["model"], resp.headers)
                    if resp.status_code < 400 and "text/event-stream" in resp.headers.get("content-type", ""):
                        return await _read_stream(resp, text)
                    raw = await resp.aread()
                    if resp.status_code < 400:
                        return json.loads(raw)  # the server ignored "stream"
                    if resp.status_code not in RETRY_STATUS or attempt >= self.max_retries:
                        raise LLMError(f"HTTP {resp.status_code}: {raw.decode(errors='replace')[:500]}")
            except httpx.TransportError as e:
                if streamed or attempt >= self.max_retries:
                    raise LLMError(f"transport error: {e}") from e
            except json.JSONDecodeError as e:
                raise LLMError(f"unexpected provider response: {e}") from e
            attempt += 1
            await asyncio.sleep(min(2**attempt, 10))

    def _note_headers(self, model: str, headers: httpx.Headers) -> None:
        """OpenAI-style x-ratelimit-* headers: per-model requests and tokens per window, reset given as "6m0s"."""
        windows = []
        for what in ("requests", "tokens"):
            limit, remaining = headers.get(f"x-ratelimit-limit-{what}"), headers.get(f"x-ratelimit-remaining-{what}")
            if not limit or remaining is None or not limit.isdigit():
                continue
            total, left = int(limit), int(remaining) if remaining.isdigit() else 0
            reset_s = _parse_duration(headers.get(f"x-ratelimit-reset-{what}", ""))
            windows.append(LimitWindow(
                label=f"{what} per minute", model=model,
                used_percent=round((total - left) / total * 100, 1) if total else 0.0,
                resets_at=(utcnow() + timedelta(seconds=reset_s)).isoformat() if reset_s is not None else None,
                detail=f"{total - left:,} of {total:,}".replace(",", " "),
            ))
        if windows:
            self._model_limits[model] = windows
            self.limits = [w for ws in self._model_limits.values() for w in ws]
            self.limits_at, self.limits_source = now_iso(), "x-ratelimit headers"

    async def fetch_limits(self) -> list[LimitWindow] | None:
        """OpenRouter exposes the key's credit usage; other HTTP providers only report limits on real calls."""
        if "openrouter.ai" not in self.base_url:
            return None
        data = (await self._request("GET", "/key")).get("data") or {}
        usage, limit = float(data.get("usage") or 0), data.get("limit")
        window = LimitWindow(
            label="credits", used_percent=round(usage / float(limit) * 100, 1) if limit else 0.0,
            detail=f"${usage:.2f} of ${float(limit):.2f}" if limit else f"${usage:.2f} spent, no limit set",
        )
        self.limits, self.limits_at, self.limits_source = [window], now_iso(), "openrouter /key"
        return self.limits

    @staticmethod
    def _parse(data: dict[str, Any]) -> ModelResponse:
        try:
            choice = data["choices"][0]
            msg = choice["message"]
        except (KeyError, IndexError) as e:
            raise LLMError(f"unexpected provider response: {str(data)[:300]}") from e
        calls = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function", {})
            args, raw, err = parse_tool_arguments(fn.get("arguments") or "{}")
            calls.append(
                ProposedToolCall(
                    id=tc.get("id") or f"call_{i}",
                    name=domain_name(fn.get("name", "")),
                    arguments=args,
                    raw_arguments=raw,
                    parse_error=err,
                )
            )
        usage = data.get("usage")
        finish = choice.get("finish_reason") or "stop"
        return ModelResponse(
            text=msg.get("content"),
            tool_calls=calls,
            finish_reason="tool_calls" if calls else ("length" if finish == "length" else "stop"),
            usage=_usage(usage, data.get("timings")) if usage else None,
            raw_provider_response=data,
        )

    async def aclose(self) -> None:
        await self._client.aclose()
