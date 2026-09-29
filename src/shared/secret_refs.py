"""Where user secrets appear in device tool arguments, and how their values are filled in and masked."""

import re
from typing import Any

PLACEHOLDER = re.compile(r"\{\{secret:([A-Z][A-Z0-9_]{1,63})\}\}")
SHELL_TOOLS = ("shell.bash", "shell.exec")
MIN_MASKED = 4


def secret_refs(tool: str, args: dict[str, Any]) -> list[str]:
    if tool in SHELL_TOOLS:
        return list(dict.fromkeys(args.get("secrets") or []))
    if tool == "net.http":
        texts = [args.get("url") or "", args.get("body") or "", *(args.get("headers") or {}).values()]
        return list(dict.fromkeys(m for t in texts for m in PLACEHOLDER.findall(t)))
    return []


def fill_secrets(args: dict[str, Any], values: dict[str, str]) -> dict[str, Any]:
    """A copy of net.http arguments with placeholders replaced; the original keeps the names."""

    def sub(text: str | None) -> str | None:
        return PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text) if text is not None else None

    return {**args, "url": sub(args["url"]), "body": sub(args.get("body")), "headers": {k: sub(v) for k, v in (args.get("headers") or {}).items()}}


def mask_secrets(text: str, values: dict[str, str]) -> str:
    for name, value in sorted(values.items(), key=lambda kv: -len(kv[1])):
        if len(value) >= MIN_MASKED:
            text = text.replace(value, f"[secret:{name}]")
    return text
