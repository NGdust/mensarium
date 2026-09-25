"""Skills: `SKILL.md` files in the Agent Skills format (agentskills.io) with a `metadata.mensarium` gating block."""

import re
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

SKILL_NAME = r"^[a-z0-9][a-z0-9-]{0,63}$"
SKILL_FILE = "SKILL.md"
OS = Literal["darwin", "linux", "win32"]
FRONTMATTER = re.compile(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*\r?\n?(.*)\Z", re.DOTALL)


class SkillError(Exception):
    pass


class SkillRequires(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tools: list[str] = Field(default=[], description="Tools that must be available on the active device, `mcp.github.*` style globs allowed")


class SkillMeta(BaseModel):
    """`metadata.mensarium`: when the skill is offered to the model."""

    model_config = ConfigDict(extra="ignore")

    always: bool = Field(default=False, description="Offer it whenever the OS matches, even if required tools are missing")
    os: list[OS] = []
    emoji: str | None = Field(default=None, max_length=8)
    requires: SkillRequires = SkillRequires()


class SkillFrontmatter(BaseModel):
    """Unknown keys of the standard (license, compatibility, allowed-tools...) are kept as they are."""

    model_config = ConfigDict(extra="allow")

    name: str = Field(pattern=SKILL_NAME)
    description: str = Field(min_length=1, max_length=1024)
    homepage: str | None = None
    metadata: dict[str, Any] = {}

    @property
    def mensarium(self) -> SkillMeta:
        block = self.metadata.get("mensarium") or self.metadata.get("openclaw") or {}
        return SkillMeta.model_validate(block if isinstance(block, dict) else {})


def parse_skill(text: str) -> tuple[SkillFrontmatter, str]:
    m = FRONTMATTER.match(text.lstrip("﻿"))
    if not m:
        raise SkillError("SKILL.md must start with a YAML frontmatter between two `---` lines")
    try:
        raw = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError as e:
        raise SkillError(f"frontmatter is not valid YAML: {e}") from e
    if not isinstance(raw, dict):
        raise SkillError("frontmatter must be a YAML mapping")
    try:
        front = SkillFrontmatter.model_validate(raw)
        _ = front.mensarium
    except ValidationError as e:
        raise SkillError("; ".join(f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in e.errors())) from e
    body = m.group(2).strip("\n")
    if not body.strip():
        raise SkillError("the skill needs instructions after the frontmatter")
    return front, body


def render_skill(front: dict[str, Any], body: str) -> str:
    """Frontmatter keys in a stable order: name, description, homepage, the rest, metadata last."""
    ordered: dict[str, Any] = {}
    for key in ("name", "description", "homepage"):
        if front.get(key) not in (None, ""):
            ordered[key] = front[key]
    for key, value in front.items():
        if key not in ordered and key != "metadata" and value not in (None, "", [], {}):
            ordered[key] = value
    if front.get("metadata"):
        ordered["metadata"] = front["metadata"]
    head = yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=1000).rstrip("\n")
    return f"---\n{head}\n---\n{body.strip(chr(10))}\n"


def compact_meta(meta: SkillMeta) -> dict[str, Any]:
    """The `metadata.mensarium` block without defaults, or {} when nothing is set."""
    out: dict[str, Any] = {}
    if meta.always:
        out["always"] = True
    if meta.os:
        out["os"] = list(meta.os)
    if meta.emoji:
        out["emoji"] = meta.emoji
    if meta.requires.tools:
        out["requires"] = {"tools": list(meta.requires.tools)}
    return out
