import logging
from typing import Any

from pydantic import ValidationError

from mensarium.agent_core.profile import AgentProfile
from mensarium.contracts.extensions import Extension, text_en
from mensarium.core.repo import Repo
from mensarium.shared.versions import parse_version
from mensarium.tool_runtime.commands import command_spec
from mensarium.tool_runtime.registry import CORE_TOOLS, REGISTRY, ToolSpec

log = logging.getLogger(__name__)


class ExtensionError(Exception):
    pass


def parse_manifests(rows: list[dict[str, Any]]) -> list[Extension]:
    out = []
    for row in rows:
        try:
            out.append(Extension.model_validate(row["manifest"]))
        except ValidationError:
            log.warning("installed extension no longer validates; skipped", extra={"extension": row["id"]})
    return out


class Toolbox:
    """Tools a task may use right now: builtins, installed command tools and Core-side tools."""

    def __init__(self, profile: AgentProfile, extensions: list[Extension]) -> None:
        self.extensions = extensions if profile.allow_extensions else []
        self.registry: dict[str, ToolSpec] = dict(REGISTRY)
        extra: list[str] = []
        for ext in self.extensions:
            for tool in ext.tools:
                if tool.name not in self.registry:
                    self.registry[tool.name] = command_spec(tool)
                    extra.append(tool.name)
        if self.skills:
            self.registry.update(CORE_TOOLS)
            extra.append("skills.read")
        self.profile_tools = [*profile.allowed_tools, *extra]

    @property
    def skills(self) -> list[tuple[str, str]]:
        return [(e.id, text_en(e.summary)) for e in self.extensions if e.instructions]

    def available(self, target: dict[str, Any]) -> list[str]:
        """Tools the model is offered on this device: reported by it and not switched off for it."""
        reported = (target.get("capabilities") or {}).get("tools", [])
        disabled = target.get("disabled_tools") or []
        out = []
        for name in self.profile_tools:
            spec = self.registry.get(name)
            if spec is None or name in disabled:
                continue
            runs_on_device = "shell.exec" if spec.command else name
            if spec.runs_on == "core" or (runs_on_device in reported and runs_on_device not in disabled):
                out.append(name)
        return out


async def check_conflicts(repo: Repo, ext: Extension) -> None:
    taken = set(REGISTRY) | set(CORE_TOOLS)
    for other in parse_manifests(await repo.list_extensions()):
        if other.id != ext.id:
            taken |= {t.name for t in other.tools}
    if clash := sorted({t.name for t in ext.tools} & taken):
        raise ExtensionError(f"tool names already taken: {', '.join(clash)}")


def listing(catalog: dict[str, Extension], rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Catalog entries and installed extensions (custom ones included) in one list for the UI."""
    installed = {r["id"]: r for r in rows}
    out = []
    for ext_id in sorted(set(catalog) | set(installed)):
        row = installed.get(ext_id)
        latest = catalog.get(ext_id)
        try:
            shown = latest or Extension.model_validate(row["manifest"] if row else {})
        except ValidationError:
            continue
        out.append(
            {
                **shown.model_dump(),
                "tools": [{**t.model_dump(), "program": t.program} for t in shown.tools],
                "installed": {"version": row["version"], "enabled": bool(row["enabled"]), "source": row["source"]}
                if row
                else None,
                "update": bool(row and latest and parse_version(latest.version) > parse_version(row["version"])),
                "in_catalog": latest is not None,
            }
        )
    return out
