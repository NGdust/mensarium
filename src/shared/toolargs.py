import json
from typing import Any


def parse_tool_arguments(raw: Any) -> tuple[dict[str, Any] | None, str, str | None]:
    """Arguments of a proposed tool call as (object, raw text, error).

    Models sometimes encode the arguments object twice (a JSON string holding the JSON object); that is unwrapped."""
    if isinstance(raw, dict):
        return raw, json.dumps(raw, ensure_ascii=False), None
    text = raw if isinstance(raw, str) else json.dumps(raw, ensure_ascii=False)
    try:
        value = json.loads(text)
        if isinstance(value, str):
            value = json.loads(value)
            if isinstance(value, dict):
                text = json.dumps(value, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return None, text, str(e)
    if not isinstance(value, dict):
        return None, text, "arguments must be a JSON object"
    return value, text, None
