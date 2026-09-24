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


class Extension(BaseModel):
    """A marketplace package: a skill (instructions for the model), command tools, or both."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,48}$")
    name: Text
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    author: str = ""
    summary: Text
    description: Text = ""
    tags: list[str] = []
    instructions: str | None = Field(None, description="Skill body in markdown, loaded by the model via skills.read")
    tools: list[CommandTool] = []

    @model_validator(mode="after")
    def _check(self) -> "Extension":
        if not self.instructions and not self.tools:
            raise ValueError("an extension needs `instructions`, `tools` or both")
        names = [t.name for t in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("tool names must be unique")
        return self
