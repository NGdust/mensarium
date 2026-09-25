import json
import re
from dataclasses import dataclass, field
from typing import Any

from mensarium.contracts.llm import ModelResponse
from mensarium.shared.ids import new_id


@dataclass
class ToolCallAction:
    call_id: str
    tool: str
    arguments: dict[str, Any] | None
    raw_arguments: str
    parse_error: str | None = None


@dataclass
class AgentAction:
    text: str
    call: ToolCallAction | None = None
    extra_calls: list[ToolCallAction] = field(default_factory=list)

    @property
    def is_final(self) -> bool:
        return self.call is None

    def assistant_tool_calls(self) -> list[dict[str, Any]]:
        calls = ([self.call] if self.call else []) + self.extra_calls
        return [{"id": c.call_id, "name": c.tool, "arguments": c.raw_arguments} for c in calls]


_JSON_BLOCK = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _json_candidates(text: str) -> list[str]:
    found = _JSON_BLOCK.findall(text)
    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        found.append(stripped)
    return found


def parse_action(resp: ModelResponse) -> AgentAction:
    """Native tool calls first; otherwise accept a {"type": "tool_call"|"final"} JSON object in the text."""
    text = (resp.text or "").strip()
    if resp.tool_calls:
        calls = [
            ToolCallAction(c.id, c.name, c.arguments, c.raw_arguments, c.parse_error) for c in resp.tool_calls
        ]
        return AgentAction(text=text, call=calls[0], extra_calls=calls[1:])
    for candidate in _json_candidates(text):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("type") == "tool_call" and isinstance(obj.get("tool"), str):
            args = obj.get("arguments")
            return AgentAction(
                text=str(obj.get("rationale") or ""),
                call=ToolCallAction(
                    call_id=new_id("call"),
                    tool=obj["tool"],
                    arguments=args if isinstance(args, dict) else None,
                    raw_arguments=json.dumps(args, ensure_ascii=False),
                    parse_error=None if isinstance(args, dict) else "arguments must be a JSON object",
                ),
            )
        if obj.get("type") == "final" and isinstance(obj.get("text"), str):
            return AgentAction(text=obj["text"])
    return AgentAction(text=text)
