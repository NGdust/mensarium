from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from mensarium.contracts.automations import Schedule


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(_Args):
    pass


class FilesListArgs(_Args):
    path: str = Field(".", description="Directory to list, absolute or relative to the workspace root")
    depth: int = Field(2, ge=1, le=5, description="How many directory levels to descend")


class FilesReadArgs(_Args):
    path: str = Field(description="File path, absolute or relative to the workspace root")
    start_line: int = Field(1, ge=1, description="First line to return (1-based)")
    max_lines: int = Field(400, ge=1, le=2000, description="Maximum number of lines to return")


class FilesSearchArgs(_Args):
    query: str = Field(min_length=1, description="Text or regex to search for")
    path: str = Field(".", description="Directory to search in")
    glob: str | None = Field(None, description="Optional file glob filter, e.g. '*.py'")
    regex: bool = Field(False, description="Treat query as a regular expression")
    max_results: int = Field(100, ge=1, le=500)


class GitStatusArgs(_Args):
    repo: str = Field(".", description="Path inside the git worktree")


class GitDiffArgs(_Args):
    repo: str = Field(".", description="Path inside the git worktree")
    staged: bool = Field(False, description="Show staged changes instead of the working tree")
    path: str | None = Field(None, description="Limit the diff to this path")


class ShellExecArgs(_Args):
    cwd: str = Field(".", description="Working directory inside the workspace")
    command: str = Field(
        min_length=1,
        description="Command line. Executed directly without a shell: no pipes, redirects, && or globs.",
    )
    stdin: str | None = Field(None, description="Optional data passed to stdin, e.g. a patch for `git apply`")
    timeout_s: int = Field(120, ge=1, le=3600)
    secrets: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Names of the user's secrets to pass as environment variables with the same names; refer to them as $NAME",
    )


class FilesStatArgs(_Args):
    path: str = Field(description="File or directory path, absolute or relative to the workspace root")


class FilesFindArgs(_Args):
    pattern: str = Field(min_length=1, description="Glob for the file name or relative path, e.g. '*.py' or 'src/**/test_*.py'")
    path: str = Field(".", description="Directory to search in")
    include_hidden: bool = Field(False, description="Also look inside dot-directories")
    max_results: int = Field(200, ge=1, le=2000)


class FilesWriteArgs(_Args):
    path: str = Field(description="File to create or overwrite, absolute or relative to the workspace root")
    content: str = Field(max_length=2_000_000, description="The whole new text of the file")
    create_dirs: bool = Field(True, description="Create missing parent directories")


class FilesEditArgs(_Args):
    path: str = Field(description="Text file to change")
    old: str = Field(min_length=1, max_length=200_000, description="Exact text to replace; must appear once unless replace_all")
    new: str = Field(max_length=200_000, description="Replacement text")
    replace_all: bool = Field(False, description="Replace every occurrence instead of requiring exactly one")


class FilesMkdirArgs(_Args):
    path: str = Field(description="Directory to create, with parents")


class FilesMoveArgs(_Args):
    source: str = Field(description="File or directory to move or rename")
    destination: str = Field(description="New path")
    overwrite: bool = Field(False, description="Replace an existing file at the destination")


class FilesCopyArgs(_Args):
    source: str = Field(description="File or directory to copy")
    destination: str = Field(description="Where the copy goes")
    overwrite: bool = Field(False, description="Replace an existing file at the destination")


class FilesDeleteArgs(_Args):
    path: str = Field(description="File or empty directory to delete")


class SystemInfoArgs(_Args):
    pass


class ProcessListArgs(_Args):
    filter: str | None = Field(None, max_length=200, description="Only processes whose command line contains this text")
    limit: int = Field(100, ge=1, le=500)


class ProcessKillArgs(_Args):
    pid: int = Field(gt=1, description="Process id from process.list")
    force: bool = Field(False, description="SIGKILL instead of SIGTERM")


class NetPortsArgs(_Args):
    pass


class NetHttpArgs(_Args):
    url: str = Field(pattern=r"^https?://", max_length=2000, description="Address, including localhost services on the device")
    method: Literal["GET", "HEAD", "POST"] = "GET"
    headers: dict[str, str] = Field(default_factory=dict, max_length=20)
    body: str | None = Field(None, max_length=200_000, description="Request body for POST")
    timeout_s: int = Field(30, ge=1, le=120)
    max_chars: int = Field(20000, ge=200, le=200_000, description="Longest response text to return")


class ShellBashArgs(_Args):
    cwd: str = Field(".", description="Working directory inside the workspace")
    script: str = Field(min_length=1, max_length=50_000, description="Bash script: pipes, redirects, loops and && are fine")
    stdin: str | None = Field(None, max_length=2_000_000, description="Optional data passed to stdin")
    timeout_s: int = Field(120, ge=1, le=3600)
    secrets: list[str] = Field(
        default_factory=list,
        max_length=20,
        description="Names of the user's secrets to pass as environment variables with the same names; refer to them as $NAME",
    )


class ScreenCaptureArgs(_Args):
    display: int = Field(1, ge=1, le=8, description="Display number, 1 is the main one")
    max_width: int = Field(1440, ge=640, le=3840, description="Downscale the screenshot to this width")


class ScreenWindowsArgs(_Args):
    pass


class InputMouseArgs(_Args):
    action: Literal["move", "click", "double_click", "right_click", "scroll"] = "click"
    x: int = Field(ge=0, description="Screen x in points, as seen on the screenshot")
    y: int = Field(ge=0, description="Screen y in points")
    scroll: int = Field(0, ge=-100, le=100, description="Scroll lines for the scroll action: positive is down")


class InputTypeArgs(_Args):
    text: str = Field(min_length=1, max_length=5000, description="Text to type into the focused window")


class InputKeyArgs(_Args):
    keys: str = Field(min_length=1, max_length=60, description="Key or combination: enter, escape, cmd+shift+t, ctrl+c")


class AppOpenArgs(_Args):
    target: str = Field(min_length=1, max_length=2000, description="Application name, file path or URL")


class SystemVolumeArgs(_Args):
    action: Literal["get", "set", "mute", "unmute"] = "get"
    level: int | None = Field(None, ge=0, le=100, description="Volume percent for the set action")


class SkillsReadArgs(_Args):
    name: str = Field(min_length=1, description="Skill name from the available_skills list in the system prompt")
    path: str | None = Field(None, max_length=300, description="Optional file inside the skill folder to read instead, e.g. references/api.md")


TOOL_ARGS: dict[str, type[_Args]] = {
    "files.list": FilesListArgs,
    "files.read": FilesReadArgs,
    "files.search": FilesSearchArgs,
    "files.stat": FilesStatArgs,
    "files.find": FilesFindArgs,
    "files.write": FilesWriteArgs,
    "files.edit": FilesEditArgs,
    "files.mkdir": FilesMkdirArgs,
    "files.move": FilesMoveArgs,
    "files.copy": FilesCopyArgs,
    "files.delete": FilesDeleteArgs,
    "git.status": GitStatusArgs,
    "git.diff": GitDiffArgs,
    "system.info": SystemInfoArgs,
    "process.list": ProcessListArgs,
    "process.kill": ProcessKillArgs,
    "net.ports": NetPortsArgs,
    "net.http": NetHttpArgs,
    "shell.exec": ShellExecArgs,
    "shell.bash": ShellBashArgs,
    "screen.capture": ScreenCaptureArgs,
    "screen.windows": ScreenWindowsArgs,
    "input.mouse": InputMouseArgs,
    "input.type": InputTypeArgs,
    "input.key": InputKeyArgs,
    "app.open": AppOpenArgs,
    "system.volume": SystemVolumeArgs,
}

class MemorySearchArgs(_Args):
    query: str = Field(min_length=1, description="Words to look for in memory note titles, tags and text")
    limit: int = Field(8, ge=1, le=20)


class MemoryReadArgs(_Args):
    title: str = Field(min_length=1, description="Exact note title")


class MemorySaveArgs(_Args):
    title: str = Field(min_length=1, max_length=120, description="Short noun phrase; reuse an existing title to add to it")
    content: str = Field(min_length=1, max_length=4000, description="What to remember, 1-4 sentences; may link [[Other note]]")
    kind: Literal["fact", "preference", "project", "person", "device", "howto"] = "fact"
    tags: list[str] = Field(default_factory=list, max_length=8)


class WebSearchArgs(_Args):
    query: str = Field(min_length=1, max_length=400, description="Search query")
    count: int | None = Field(None, ge=1, le=20, description="Number of results, the plugin setting by default")


class WebFetchArgs(_Args):
    url: str = Field(pattern=r"^https?://", max_length=2000, description="Page address, http or https")
    max_chars: int = Field(20000, ge=500, le=100000, description="Longest text to return")


class GmailSearchArgs(_Args):
    query: str = Field(min_length=1, max_length=500, description="Gmail search query, e.g. 'from:alice newer_than:7d'")
    max_results: int = Field(10, ge=1, le=25, description="How many messages to list")


class GmailReadArgs(_Args):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$", description="Message id from gmail.search")


class GmailSendArgs(_Args):
    to: str = Field(min_length=3, max_length=500, description="Recipient addresses, comma separated")
    subject: str = Field(max_length=500, description="Subject line")
    body: str = Field(min_length=1, max_length=50000, description="Plain-text body")
    reply_to_id: str | None = Field(None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$", description="Message id to reply to, keeps the thread")


class DriveSearchArgs(_Args):
    query: str = Field(min_length=1, max_length=500, description="Words to find, or a Drive query like \"name contains 'report'\"")
    max_results: int = Field(10, ge=1, le=25, description="How many files to list")


class DriveReadArgs(_Args):
    id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$", description="File id from drive.search")


class PluginsFindArgs(_Args):
    query: str = Field(min_length=1, max_length=200, description="What the plugin should do: 'web search', 'github', 'postgres', 'browser'")


class PluginsInstallArgs(_Args):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,48}$", description="Plugin id from plugins.find")


class PlanItem(_Args):
    title: str = Field(min_length=1, max_length=200, description="One step of the plan, in the user's language")
    status: Literal["pending", "in_progress", "done"] = "pending"


class PlanUpdateArgs(_Args):
    items: list[PlanItem] = Field(max_length=20, description="The whole plan; it replaces the previous one")


class AgentSpawnArgs(_Args):
    label: str = Field(min_length=1, max_length=60, description="Short name shown to the user, e.g. 'tests' or 'API research'")
    task: str = Field(min_length=1, max_length=20_000, description="Complete instructions: the sub-agent sees only this text, not your conversation")
    model: str | None = Field(None, max_length=200, description="Model id for this sub-agent; the chat's model by default")


class AgentWaitArgs(_Args):
    ids: list[str] = Field(default_factory=list, max_length=20, description="Sub-agent ids to wait for; all of them when empty")


class AutomationsCreateArgs(_Args):
    name: str = Field(min_length=1, max_length=120, description="Short name shown in the automations list")
    prompt: str = Field(min_length=1, max_length=20_000, description="Complete instructions for each run; the run does not see this chat")
    schedule: Schedule
    notify: bool = Field(True, description="Send each result to the user's Telegram when it is connected")


class AutomationsDeleteArgs(_Args):
    id: str = Field(pattern=r"^auto_[0-9A-Za-z]+$")


class McpArgs(BaseModel):
    """MCP tools bring their own JSON schema; the harness checks it separately."""

    model_config = ConfigDict(extra="allow")


CORE_TOOL_ARGS: dict[str, type[BaseModel]] = {
    "skills.read": SkillsReadArgs,
    "memory.search": MemorySearchArgs,
    "memory.read": MemoryReadArgs,
    "memory.save": MemorySaveArgs,
    "web.search": WebSearchArgs,
    "web.fetch": WebFetchArgs,
    "gmail.search": GmailSearchArgs,
    "gmail.read": GmailReadArgs,
    "gmail.send": GmailSendArgs,
    "drive.search": DriveSearchArgs,
    "drive.read": DriveReadArgs,
    "plugins.find": PluginsFindArgs,
    "plugins.install": PluginsInstallArgs,
    "plan.update": PlanUpdateArgs,
    "agent.spawn": AgentSpawnArgs,
    "agent.wait": AgentWaitArgs,
    "automations.list": NoArgs,
    "automations.create": AutomationsCreateArgs,
    "automations.delete": AutomationsDeleteArgs,
    "device.update": NoArgs,
}

PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "files.list": ("path",),
    "files.read": ("path",),
    "files.search": ("path",),
    "files.stat": ("path",),
    "files.find": ("path",),
    "files.write": ("path",),
    "files.edit": ("path",),
    "files.mkdir": ("path",),
    "files.move": ("source", "destination"),
    "files.copy": ("source", "destination"),
    "files.delete": ("path",),
    "git.status": ("repo",),
    "git.diff": ("repo",),
    "shell.exec": ("cwd",),
    "shell.bash": ("cwd",),
}

WRITE_PATH_TOOLS = ("files.write", "files.edit", "files.mkdir", "files.move", "files.copy", "files.delete")
