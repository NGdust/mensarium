from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from mensarium.contracts.extensions import CommandTool
from mensarium.contracts.llm import ToolDefinition
from mensarium.contracts.tools import CORE_TOOL_ARGS, TOOL_ARGS

Risk = Literal["read", "write", "execute", "network", "destructive", "privileged"]
RunsOn = Literal["target", "core"]


@dataclass(frozen=True)
class ToolSpec:
    """`runs_on="core"` tools touch only Core data; `command` tools run on the device as shell.exec."""

    name: str
    description: str
    risk: Risk
    args_model: type[BaseModel]
    display: Callable[[dict[str, Any]], str]
    runs_on: RunsOn = "target"
    command: CommandTool | None = None

    def definition(self) -> ToolDefinition:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return ToolDefinition(name=self.name, description=self.description, parameters=schema)


def _shell_display(a: dict[str, Any]) -> str:
    text = f"$ {a['command']}  (cwd: {a['cwd']})"
    if a.get("stdin"):
        text += f"  [stdin: {len(a['stdin'])} bytes]"
    return text


_SPECS = [
    ToolSpec(
        "files.list",
        "List files and directories inside an allowed workspace root.",
        "read",
        TOOL_ARGS["files.list"],
        lambda a: f"ls {a['path']} (depth {a['depth']})",
    ),
    ToolSpec(
        "files.read",
        "Read a text file inside an allowed workspace root. Secrets are redacted.",
        "read",
        TOOL_ARGS["files.read"],
        lambda a: f"read {a['path']}:{a['start_line']}+{a['max_lines']}",
    ),
    ToolSpec(
        "files.search",
        "Search file contents (ripgrep) inside an allowed workspace root.",
        "read",
        TOOL_ARGS["files.search"],
        lambda a: f"search {a['query']!r} in {a['path']}" + (f" ({a['glob']})" if a.get("glob") else ""),
    ),
    ToolSpec(
        "git.status",
        "Show `git status` for a repository inside an allowed root.",
        "read",
        TOOL_ARGS["git.status"],
        lambda a: f"git status ({a['repo']})",
    ),
    ToolSpec(
        "git.diff",
        "Show `git diff` for a repository inside an allowed root.",
        "read",
        TOOL_ARGS["git.diff"],
        lambda a: f"git diff{' --staged' if a['staged'] else ''} ({a['repo']})"
        + (f" -- {a['path']}" if a.get("path") else ""),
    ),
    ToolSpec(
        "shell.exec",
        "Run one allowlisted program in a workspace directory. No shell: pipes, redirects, `&&`, "
        "`cd` and globs do not work; use `cwd` instead. To modify files, pass a unified diff via "
        "`stdin` to `git apply` (or `patch -p1`). Every call requires explicit user approval.",
        "execute",
        TOOL_ARGS["shell.exec"],
        _shell_display,
    ),
]

REGISTRY: dict[str, ToolSpec] = {s.name: s for s in _SPECS}

CORE_TOOLS: dict[str, ToolSpec] = {
    "skills.read": ToolSpec(
        "skills.read",
        "Load the full instructions of an installed skill. Call it before doing work a listed skill covers.",
        "read",
        CORE_TOOL_ARGS["skills.read"],
        lambda a: f"skill {a['id']}",
        runs_on="core",
    ),
}
