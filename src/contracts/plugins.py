import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = str | dict[str, str]
PLACEHOLDER = re.compile(r"\{(\w+)\}")
TOOL_NAME = r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"


def text_en(value: Text) -> str:
    return value if isinstance(value, str) else value.get("en") or next(iter(value.values()), "")


class ParamSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "number", "boolean"] = "string"
    description: str = ""
    default: Any = None
    required: bool = False
    enum: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    pattern: str | None = None
    flag: str | None = Field(None, description="For booleans: the literal argument inserted when true")
    allow_flags: bool = Field(False, description="Allow string values that start with '-'")


class CommandTool(BaseModel):
    """A tool that runs one allowlisted program on the device; arguments fill whole argv elements."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=TOOL_NAME)
    description: str = Field(min_length=1)
    risk: Literal["read", "write", "execute", "network", "destructive"] = "execute"
    argv: list[str] = Field(min_length=1)
    cwd: str = "."
    timeout_s: int = Field(120, ge=1, le=3600)
    parameters: dict[str, ParamSpec] = {}

    @property
    def program(self) -> str:
        return self.argv[0]

    @model_validator(mode="after")
    def _check(self) -> "CommandTool":
        if PLACEHOLDER.search(self.argv[0]) or "/" in self.argv[0]:
            raise ValueError(f"{self.name}: argv[0] must be a program name without placeholders")
        used = {m for part in [*self.argv, self.cwd] for m in PLACEHOLDER.findall(part)}
        if missing := used - set(self.parameters):
            raise ValueError(f"{self.name}: undeclared parameters {sorted(missing)}")
        for name, p in self.parameters.items():
            if p.type == "boolean" and any(PLACEHOLDER.fullmatch(a) and a[1:-1] == name for a in self.argv) and not p.flag:
                raise ValueError(f"{self.name}: boolean parameter {name!r} used in argv needs `flag`")
        return self


Risk = Literal["read", "write", "execute", "network", "destructive"]
BUILTINS = ("web_search", "web_fetch")


class ConfigField(BaseModel):
    """One plugin setting; secret values live in Core secrets and never reach the model, the UI or devices."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["string", "integer", "number", "boolean"] = "string"
    title: Text | None = None
    help: Text | None = None
    default: Any = None
    required: bool = False
    secret: bool = False
    enum: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    placeholder: str | None = None
    flag: str | None = Field(None, description="For booleans used in an MCP template: the argument inserted when true")


class McpTemplate(BaseModel):
    """An MCP server the plugin starts; `{key}` placeholders are filled from the plugin config."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    headers: dict[str, str] = {}
    placement: Literal["core", "device"] = "core"
    risk: Risk = "network"

    @model_validator(mode="after")
    def _check(self) -> "McpTemplate":
        if self.transport == "stdio" and (not self.command or "/" in self.command or PLACEHOLDER.search(self.command)):
            raise ValueError("stdio MCP servers need `command`: a program name without a path or placeholders")
        if self.transport == "http" and not (self.url or "").startswith(("http://", "https://", "{")):
            raise ValueError("http MCP servers need an http(s) `url`")
        return self

    def placeholders(self) -> set[str]:
        parts = [*self.args, *self.env.values(), self.url or "", *self.headers.values()]
        return {m for part in parts for m in PLACEHOLDER.findall(part)}


class Plugin(BaseModel):
    """A plugin: command tools for devices, a built-in Core tool, an MCP server, or a mix."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,48}$")
    name: Text
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    author: str = ""
    summary: Text
    description: Text = ""
    tags: list[str] = []
    homepage: str | None = None
    config: dict[str, ConfigField] = {}
    tools: list[CommandTool] = []
    builtin: Literal["web_search", "web_fetch"] | None = Field(None, description="Core tools shipped with Mensarium")
    mcp: McpTemplate | None = None

    @model_validator(mode="after")
    def _check(self) -> "Plugin":
        if not (self.tools or self.builtin or self.mcp):
            raise ValueError("a plugin needs `tools`, `builtin` or `mcp`; instructions for the model are skills, not plugins")
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        if self.mcp and (missing := self.mcp.placeholders() - set(self.config)):
            raise ValueError(f"mcp uses undeclared config keys {sorted(missing)}")
        return self

    def secret_keys(self) -> set[str]:
        return {k for k, f in self.config.items() if f.secret}
