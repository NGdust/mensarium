from typing import Any, Literal

from pydantic import BaseModel, Field


class Message(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[dict[str, Any]] | None = Field(None, description="Text, or content parts (text and image_url) for images")
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ChatRequest(BaseModel):
    model: str
    system: str
    messages: list[Message]
    temperature: float = 0.2
    max_output_tokens: int = 1200
    timeout_s: int = 90
    metadata: dict[str, str] = {}


class ProposedToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] | None
    raw_arguments: str
    parse_error: str | None = None


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0


class ModelResponse(BaseModel):
    text: str | None
    tool_calls: list[ProposedToolCall]
    finish_reason: Literal["stop", "tool_calls", "length", "error"]
    usage: TokenUsage | None = None
    raw_provider_response: dict[str, Any] = {}


class ModelInfo(BaseModel):
    id: str


class ProviderHealth(BaseModel):
    ok: bool
    detail: str = ""
