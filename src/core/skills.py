"""Skills the model can load: bundled `SKILL.md` folders plus the user's own under ~/.mensarium/skills."""

import fnmatch
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mensarium.contracts.plugins import text_en
from mensarium.contracts.skills import (
    SKILL_FILE,
    SkillError,
    SkillFrontmatter,
    SkillMeta,
    compact_meta,
    parse_skill,
    render_skill,
)
from mensarium.core.repo import Repo
from mensarium.shared.paths import write_private
from mensarium.skills import bundled_dir

log = logging.getLogger(__name__)

DISABLED_KEY = "skills.disabled"
MAX_FILE_BYTES = 200_000
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".toml", ".csv", ".py", ".sh", ".js", ".ts", ".html", ".css", ".xml"}


@dataclass
class Skill:
    front: SkillFrontmatter
    body: str
    source: str
    path: Path
    enabled: bool = True
    shadows: bool = field(default=False, init=False)

    @property
    def name(self) -> str:
        return self.front.name

    @property
    def description(self) -> str:
        return self.front.description

    @property
    def meta(self) -> SkillMeta:
        return self.front.mensarium

    def files(self) -> list[str]:
        out = []
        for f in sorted(self.path.rglob("*")):
            if f.is_file() and f.name != SKILL_FILE and not any(p.startswith(".") for p in f.relative_to(self.path).parts):
                out.append(f.relative_to(self.path).as_posix())
        return out[:200]

    def view(self) -> dict[str, Any]:
        meta = self.meta
        return {
            "name": self.name,
            "description": self.description,
            "homepage": self.front.homepage,
            "emoji": meta.emoji,
            "always": meta.always,
            "os": list(meta.os),
            "requires_tools": list(meta.requires.tools),
            "source": self.source,
            "enabled": self.enabled,
            "shadows": self.shadows,
            "files": self.files(),
        }


class SkillStore:
    def __init__(self, repo: Repo, workspace_id: str, user_dir: Path, bundled: Path | None = None) -> None:
        self.repo = repo
        self.workspace_id = workspace_id
        self.user_dir = user_dir
        self.bundled = bundled or bundled_dir()

    # ---- reading ------------------------------------------------------------

    async def all(self) -> list[Skill]:
        disabled = set(await self.repo.get_setting(DISABLED_KEY) or [])
        skills: dict[str, Skill] = {}
        for skill in self._scan(self.bundled, "bundled"):
            skills[skill.name] = skill
        for skill in self._scan(self.user_dir, "user"):
            skill.shadows = skill.name in skills
            skills[skill.name] = skill
        for skill in skills.values():
            skill.enabled = skill.name not in disabled
        return sorted(skills.values(), key=lambda s: s.name)

    async def get(self, name: str) -> Skill:
        for skill in await self.all():
            if skill.name == name:
                return skill
        raise SkillError(f"skill {name!r} not found")

    def _scan(self, root: Path, source: str) -> list[Skill]:
        out: list[Skill] = []
        if not root.is_dir():
            return out
        for folder in sorted(root.iterdir()):
            f = folder / SKILL_FILE
            if not folder.is_dir() or not f.is_file():
                continue
            try:
                front, body = parse_skill(f.read_text(encoding="utf-8", errors="replace"))
            except SkillError as e:
                log.warning("skipped invalid skill", extra={"path": str(f), "error": str(e)})
                continue
            if front.name != folder.name:
                log.warning("skill folder name and frontmatter name differ; using the frontmatter", extra={"path": str(f)})
            out.append(Skill(front, body, source, folder))
        return out

    @staticmethod
    def eligible(skills: list[Skill], platform: str, tools: list[str]) -> list[Skill]:
        """Skills offered on this device: enabled, OS matches, required tools are available (unless `always`)."""
        os_name = platform.split("-")[0]
        out = []
        for skill in skills:
            meta = skill.meta
            if not skill.enabled or (meta.os and os_name not in meta.os):
                continue
            if not meta.always and not all(any(fnmatch.fnmatchcase(t, pattern) for t in tools) for pattern in meta.requires.tools):
                continue
            out.append(skill)
        return out

    @staticmethod
    def read(skill: Skill, path: str | None = None) -> str:
        if not path:
            return f"[skill {skill.name}, installed by the user]\n{skill.body}"
        root = skill.path.resolve()
        target = (root / path).resolve()
        if path.startswith(("/", "~")) or root not in target.parents:
            raise SkillError(f"{path!r} is outside the skill folder")
        if not target.is_file():
            raise SkillError(f"the skill has no file {path!r}; it ships: {', '.join(skill.files()) or 'nothing else'}")
        if target.suffix.lower() not in TEXT_SUFFIXES:
            raise SkillError(f"{path!r} is not a text file")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise SkillError(f"{path!r} is larger than {MAX_FILE_BYTES // 1000} KB")
        return f"[skill {skill.name}, file {path}]\n{target.read_text(encoding='utf-8', errors='replace')}"

    # ---- writing ------------------------------------------------------------

    async def save(
        self,
        name: str,
        description: str,
        body: str,
        meta: SkillMeta,
        homepage: str | None = None,
    ) -> Skill:
        """Write the user's copy; unknown frontmatter keys of an existing user file are kept."""
        front: dict[str, Any] = {}
        current = self.user_dir / name / SKILL_FILE
        if current.is_file():
            try:
                front = parse_skill(current.read_text(encoding="utf-8", errors="replace"))[0].model_dump()
            except SkillError:
                front = {}
        metadata = {k: v for k, v in (front.get("metadata") or {}).items() if k not in ("mensarium", "openclaw")}
        if block := compact_meta(meta):
            metadata["mensarium"] = block
        front |= {"name": name, "description": description, "homepage": homepage or None, "metadata": metadata}
        return await self.save_text(render_skill(front, body), expect=name)

    async def save_text(self, text: str, expect: str | None = None) -> Skill:
        front, _ = parse_skill(text)
        if expect and front.name != expect:
            raise SkillError(f"the frontmatter says name: {front.name}, expected {expect}")
        write_private(self.user_dir / front.name / SKILL_FILE, text if text.endswith("\n") else text + "\n")
        await self.repo.audit(self.workspace_id, "user", "skill.saved", {"name": front.name})
        return await self.get(front.name)

    async def delete(self, name: str) -> None:
        folder = self.user_dir / name
        if not (folder / SKILL_FILE).is_file():
            raise SkillError(f"{name!r} is not one of your skills" if (self.bundled / name).is_dir() else f"skill {name!r} not found")
        shutil.rmtree(folder)
        await self.repo.audit(self.workspace_id, "user", "skill.removed", {"name": name})

    async def set_enabled(self, name: str, enabled: bool) -> Skill:
        await self.get(name)
        disabled = set(await self.repo.get_setting(DISABLED_KEY) or [])
        (disabled.discard if enabled else disabled.add)(name)
        await self.repo.set_setting(DISABLED_KEY, sorted(disabled))
        await self.repo.audit(self.workspace_id, "user", "skill.toggled", {"name": name, "enabled": enabled})
        return await self.get(name)

    # ---- migration from plugin manifests ------------------------------------

    async def adopt_plugins(self) -> None:
        """Skills that used to be plugins with `instructions` become SKILL.md files; mixed plugins lose the text."""
        for row in await self.repo.list_plugins():
            manifest = dict(row["manifest"])
            text = manifest.pop("instructions", None)
            if not text:
                continue
            name = manifest["id"]
            pure = not (manifest.get("tools") or manifest.get("builtin") or manifest.get("mcp"))
            bundled = (self.bundled / name / SKILL_FILE).is_file()
            if not bundled or row["source"] == "custom":
                try:
                    await self.save(name, text_en(manifest.get("summary") or name), str(text), SkillMeta())
                except SkillError as e:
                    log.warning("could not turn the plugin into a skill", extra={"plugin": name, "error": str(e)})
                    continue
            if not row["enabled"]:
                await self.set_enabled(name, False)
            if pure:
                await self.repo.delete_plugin(name)
            else:
                await self.repo.update_plugin(name, {"manifest": manifest})
            log.info("plugin skill moved to the skills folder", extra={"plugin": name})
