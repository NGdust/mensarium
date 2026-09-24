import shlex
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, create_model

from mensarium.contracts.extensions import PLACEHOLDER, CommandTool, ParamSpec
from mensarium.tool_runtime.registry import ToolSpec

_TYPES: dict[str, type] = {"string": str, "integer": int, "number": float, "boolean": bool}


def _field(p: ParamSpec) -> tuple[Any, Any]:
    kind: Any = Literal[tuple(p.enum)] if p.enum else _TYPES[p.type]  # type: ignore[misc]
    constraints: dict[str, Any] = {"description": p.description or None}
    if p.minimum is not None:
        constraints["ge"] = p.minimum
    if p.maximum is not None:
        constraints["le"] = p.maximum
    if p.pattern and p.type == "string":
        constraints["pattern"] = p.pattern
    if p.required:
        return kind, Field(**constraints)
    return kind | None, Field(p.default, **constraints)


def args_model(tool: CommandTool) -> type[BaseModel]:
    fields = {name: _field(p) for name, p in tool.parameters.items()}
    return create_model(  # type: ignore[call-overload,no-any-return]
        "Args_" + tool.name.replace(".", "_"), __config__=ConfigDict(extra="forbid"), **fields
    )


def _value(tool: CommandTool, name: str, args: dict[str, Any]) -> str | None:
    p = tool.parameters[name]
    value = args.get(name)
    if p.type == "boolean":
        return p.flag if value else None
    if value is None or value == "":
        return None
    text = str(value)
    if text.startswith("-") and not p.allow_flags:
        raise ValueError(f"parameter {name!r} must not start with '-'")
    return text


def _substitute(tool: CommandTool, part: str, args: dict[str, Any]) -> str | None:
    """Whole-element placeholders drop the element when empty; inline ones drop it when any value is empty."""
    values = {n: _value(tool, n, args) for n in PLACEHOLDER.findall(part)}
    if any(v is None for v in values.values()):
        return None
    return PLACEHOLDER.sub(lambda m: values[m.group(1)] or "", part)


def render(tool: CommandTool, args: dict[str, Any]) -> dict[str, Any]:
    """Validated tool arguments -> shell.exec arguments. Each value stays one argv element."""
    argv = [v for part in tool.argv if (v := _substitute(tool, part, args)) is not None]
    return {"command": shlex.join(argv), "cwd": _substitute(tool, tool.cwd, args) or ".", "timeout_s": tool.timeout_s}


def command_spec(tool: CommandTool) -> ToolSpec:
    return ToolSpec(
        name=tool.name,
        description=f"{tool.description} Runs `{tool.program}` on the device.",
        risk=tool.risk,
        args_model=args_model(tool),
        display=lambda a: f"{tool.name}: $ {a['command']}  (cwd: {a['cwd']})",
        command=tool,
    )
