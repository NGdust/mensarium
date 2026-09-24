from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


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


class SkillsReadArgs(_Args):
    id: str = Field(min_length=1, description="Skill id from the skills list in the system prompt")


TOOL_ARGS: dict[str, type[_Args]] = {
    "files.list": FilesListArgs,
    "files.read": FilesReadArgs,
    "files.search": FilesSearchArgs,
    "git.status": GitStatusArgs,
    "git.diff": GitDiffArgs,
    "shell.exec": ShellExecArgs,
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


CORE_TOOL_ARGS: dict[str, type[_Args]] = {
    "skills.read": SkillsReadArgs,
    "memory.search": MemorySearchArgs,
    "memory.read": MemoryReadArgs,
    "memory.save": MemorySaveArgs,
}

PATH_FIELDS: dict[str, tuple[str, ...]] = {
    "files.list": ("path",),
    "files.read": ("path",),
    "files.search": ("path",),
    "git.status": ("repo",),
    "git.diff": ("repo",),
    "shell.exec": ("cwd",),
}
