from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from mensarium.contracts.llm import ToolDefinition
from mensarium.contracts.plugins import CommandTool
from mensarium.contracts.tools import CORE_TOOL_ARGS, TOOL_ARGS

Risk = Literal["read", "write", "execute", "network", "destructive", "privileged"]
RunsOn = Literal["target", "core"]


@dataclass(frozen=True)
class ToolSpec:
    """`runs_on="core"` tools run inside the Core; `command` tools run on the device as shell.exec and
    `mcp` tools are (server, tool) of an MCP server in the Core or on the device. `always_ask` tools wait
    for the user's approval even in full access mode."""

    name: str
    description: str
    risk: Risk
    args_model: type[BaseModel]
    display: Callable[[dict[str, Any]], str]
    runs_on: RunsOn = "target"
    command: CommandTool | None = None
    mcp: tuple[str, str] | None = None
    schema: dict[str, Any] | None = None
    always_ask: bool = False

    def definition(self) -> ToolDefinition:
        schema = dict(self.schema) if self.schema else self.args_model.model_json_schema()
        schema.pop("title", None)
        schema.pop("$schema", None)
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
        "files.stat",
        "Type, size, permissions, modification time and line count of a path inside an allowed root.",
        "read",
        TOOL_ARGS["files.stat"],
        lambda a: f"stat {a['path']}",
    ),
    ToolSpec(
        "files.find",
        "Find files by name glob inside an allowed root, e.g. '*.py' or 'src/**/test_*.py'. Skips .git, node_modules and secret folders.",
        "read",
        TOOL_ARGS["files.find"],
        lambda a: f"find {a['pattern']!r} in {a['path']}",
    ),
    ToolSpec(
        "files.write",
        "Create or overwrite a whole text file inside an allowed root (atomic). Prefer files.edit for small changes.",
        "write",
        TOOL_ARGS["files.write"],
        lambda a: f"write {a['path']} ({len(a['content'])} chars)",
    ),
    ToolSpec(
        "files.edit",
        "Replace an exact text fragment in a file. `old` must match exactly once (or set replace_all). Returns the diff.",
        "write",
        TOOL_ARGS["files.edit"],
        lambda a: f"edit {a['path']}: replace {len(a['old'])} chars with {len(a['new'])}" + (" (all)" if a.get("replace_all") else ""),
    ),
    ToolSpec(
        "files.mkdir",
        "Create a directory (with parents) inside an allowed root.",
        "write",
        TOOL_ARGS["files.mkdir"],
        lambda a: f"mkdir {a['path']}",
    ),
    ToolSpec(
        "files.move",
        "Move or rename a file or directory inside the allowed roots.",
        "write",
        TOOL_ARGS["files.move"],
        lambda a: f"move {a['source']} -> {a['destination']}",
    ),
    ToolSpec(
        "files.copy",
        "Copy a file or directory inside the allowed roots.",
        "write",
        TOOL_ARGS["files.copy"],
        lambda a: f"copy {a['source']} -> {a['destination']}",
    ),
    ToolSpec(
        "files.delete",
        "Delete one file or an empty directory. Not recursive. Always confirmed by the user.",
        "destructive",
        TOOL_ARGS["files.delete"],
        lambda a: f"delete {a['path']}",
    ),
    ToolSpec(
        "system.info",
        "OS, architecture, CPU, memory, load, disk space of the allowed roots, uptime and agent version of the device.",
        "read",
        TOOL_ARGS["system.info"],
        lambda a: "system info",
    ),
    ToolSpec(
        "process.list",
        "Running processes on the device: pid, cpu, memory, user and command line, optionally filtered by text.",
        "read",
        TOOL_ARGS["process.list"],
        lambda a: "process list" + (f" matching {a['filter']!r}" if a.get("filter") else ""),
    ),
    ToolSpec(
        "process.kill",
        "Stop a process of the device's user by pid (SIGTERM, or SIGKILL with force). Always confirmed by the user.",
        "destructive",
        TOOL_ARGS["process.kill"],
        lambda a: f"kill {a['pid']}" + (" -9" if a.get("force") else ""),
    ),
    ToolSpec(
        "net.ports",
        "Listening TCP/UDP ports on the device and the processes behind them.",
        "read",
        TOOL_ARGS["net.ports"],
        lambda a: "listening ports",
    ),
    ToolSpec(
        "net.http",
        "HTTP request from the device itself: reach localhost services, dev servers and internal APIs. Returns status, headers and text.",
        "network",
        TOOL_ARGS["net.http"],
        lambda a: f"{a['method']} {a['url']}",
    ),
    ToolSpec(
        "shell.exec",
        "Run one allowlisted program in a workspace directory. No shell: pipes, redirects, `&&`, "
        "`cd` and globs do not work; use `cwd` instead. Every call requires explicit user approval.",
        "execute",
        TOOL_ARGS["shell.exec"],
        _shell_display,
    ),
    ToolSpec(
        "shell.bash",
        "Run a bash script in a workspace directory: pipes, redirects, loops, `&&` and any installed program. "
        "The user reviews and approves every script; sudo and other privileged commands are refused.",
        "execute",
        TOOL_ARGS["shell.bash"],
        lambda a: f"$ {a['script'] if len(a['script']) <= 200 else a['script'][:200] + '…'}  (cwd: {a['cwd']})"
        + (f"  [stdin: {len(a['stdin'])} bytes]" if a.get("stdin") else ""),
    ),
    ToolSpec(
        "screen.capture",
        "Take a screenshot of the device's screen; you receive it as an image, and the last screenshot of your turn "
        "is attached to your reply in the user's chat. Use it when the user asks for a screenshot or to see the screen, "
        "to find coordinates before input.mouse and to verify the result after acting.",
        "execute",
        TOOL_ARGS["screen.capture"],
        lambda a: f"screenshot of display {a['display']}",
    ),
    ToolSpec(
        "screen.windows",
        "List open applications and windows with their positions and sizes, and which one is in front.",
        "read",
        TOOL_ARGS["screen.windows"],
        lambda a: "list windows",
    ),
    ToolSpec(
        "input.mouse",
        "Move, click, double-click, right-click or scroll at screen coordinates taken from a screenshot.",
        "execute",
        TOOL_ARGS["input.mouse"],
        lambda a: f"mouse {a['action']} at {a['x']},{a['y']}" + (f" by {a['scroll']}" if a.get("scroll") else ""),
    ),
    ToolSpec(
        "input.type",
        "Type text into the focused window on the device.",
        "execute",
        TOOL_ARGS["input.type"],
        lambda a: f"type {len(a['text'])} characters",
    ),
    ToolSpec(
        "input.key",
        "Press a key or combination on the device: enter, escape, cmd+shift+t, ctrl+c.",
        "execute",
        TOOL_ARGS["input.key"],
        lambda a: f"press {a['keys']}",
    ),
    ToolSpec(
        "app.open",
        "Open an application, a file or a URL on the device.",
        "execute",
        TOOL_ARGS["app.open"],
        lambda a: f"open {a['target']}",
    ),
    ToolSpec(
        "system.volume",
        "Read or change the output volume of the device, or mute and unmute it.",
        "execute",
        TOOL_ARGS["system.volume"],
        lambda a: f"volume {a['action']}" + (f" {a['level']}%" if a.get("level") is not None else ""),
    ),
]

REGISTRY: dict[str, ToolSpec] = {s.name: s for s in _SPECS}

CORE_TOOLS: dict[str, ToolSpec] = {
    "skills.read": ToolSpec(
        "skills.read",
        "Load the full instructions of a skill from available_skills. Call it before doing work a skill covers; "
        "pass `path` to read a file the skill's instructions point to.",
        "read",
        CORE_TOOL_ARGS["skills.read"],
        lambda a: f"skill {a['name']}" + (f" {a['path']}" if a.get("path") else ""),
        runs_on="core",
    ),
}

MEMORY_TOOLS: dict[str, ToolSpec] = {
    "memory.search": ToolSpec(
        "memory.search",
        "Search long-term memory notes about the user, projects and devices. Use it before asking the user "
        "something they may have told you before.",
        "read",
        CORE_TOOL_ARGS["memory.search"],
        lambda a: f"memory search {a['query']!r}",
        runs_on="core",
    ),
    "memory.read": ToolSpec(
        "memory.read",
        "Read one memory note in full, with the notes that link to it.",
        "read",
        CORE_TOOL_ARGS["memory.read"],
        lambda a: f"memory read {a['title']}",
        runs_on="core",
    ),
    "memory.save": ToolSpec(
        "memory.save",
        "Remember a durable fact for future tasks: a user preference, a project fact, a decision or a fix. "
        "Adds a note or appends to the note with the same title; never store secrets or command output.",
        "read",
        CORE_TOOL_ARGS["memory.save"],
        lambda a: f"memory save {a['title']}",
        runs_on="core",
    ),
}

PLUGIN_TOOLS: dict[str, ToolSpec] = {
    "plugins.find": ToolSpec(
        "plugins.find",
        "Search the Mensarium plugin catalog for a plugin that adds a capability you lack: web search, reading "
        "web pages, GitHub, databases, a browser, cloud and chat services. Shows what each plugin needs to work.",
        "read",
        CORE_TOOL_ARGS["plugins.find"],
        lambda a: f"find plugin {a['query']!r}",
        runs_on="core",
    ),
    "plugins.install": ToolSpec(
        "plugins.install",
        "Install and turn on a catalog plugin by id, or turn on an installed one. The user approves every call; "
        "the plugin's tools are available from the next step.",
        "execute",
        CORE_TOOL_ARGS["plugins.install"],
        lambda a: f"install plugin {a['id']}",
        runs_on="core",
        always_ask=True,
    ),
}

PLAN_TOOLS: dict[str, ToolSpec] = {
    "plan.update": ToolSpec(
        "plan.update",
        "Write or update the plan the user sees above the chat input: the whole list of steps with their status "
        "(pending, in_progress, done). Call it before starting a task with several steps and again each time a step "
        "starts or finishes; keep titles short and in the user's language.",
        "read",
        CORE_TOOL_ARGS["plan.update"],
        lambda a: f"plan: {sum(i['status'] == 'done' for i in a['items'])}/{len(a['items'])} done",
        runs_on="core",
    ),
}

AGENT_TOOLS: dict[str, ToolSpec] = {
    "agent.spawn": ToolSpec(
        "agent.spawn",
        "Start a sub-agent that works in parallel on the same device with the same tools and permissions. It sees "
        "only the task text you give it, so include every file path, constraint and the expected report. Returns its id "
        "at once; get its report with agent.wait. Use it for independent parts of a big task or parallel research, "
        "not for a single quick action.",
        "read",
        CORE_TOOL_ARGS["agent.spawn"],
        lambda a: f"agent {a['label']}",
        runs_on="core",
    ),
    "agent.wait": ToolSpec(
        "agent.wait",
        "Wait until the given sub-agents (all of them when ids is empty) finish and return their reports.",
        "read",
        CORE_TOOL_ARGS["agent.wait"],
        lambda a: "wait for " + (", ".join(a["ids"]) if a["ids"] else "all agents"),
        runs_on="core",
    ),
}
