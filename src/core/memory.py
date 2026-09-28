import re
from typing import Any

from mensarium.core.repo import Repo
from mensarium.shared.ids import new_id
from mensarium.shared.redaction import redact

KINDS = ("fact", "preference", "project", "person", "device", "howto", "note")
WIKILINK = re.compile(r"\[\[([^\[\]|#\n]+?)(?:\|[^\[\]\n]*)?\]\]")
BAD_TITLE = re.compile(r"[\[\]|#\n]")
TITLE_MAX = 120
BODY_MAX = 20000
CONTEXT_BUDGET = 2500
CENTER_KEY = "memory.center"


class NoteError(Exception):
    pass


def wikilinks(body: str) -> list[str]:
    seen: dict[str, str] = {}
    for m in WIKILINK.finditer(body or ""):
        title = m.group(1).strip()
        seen.setdefault(title.lower(), title)
    return list(seen.values())


def clean_title(title: str) -> str:
    title = " ".join((title or "").split())
    if not title or len(title) > TITLE_MAX or BAD_TITLE.search(title):
        raise NoteError(f"title must be 1-{TITLE_MAX} characters without [ ] | #")
    return title


def clean_tags(tags: list[str] | tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for t in tags:
        tag = "-".join(str(t).strip().lstrip("#").lower().split())[:40]
        if tag and tag not in out:
            out.append(tag)
    return out[:12]


def snippet(body: str, query_terms: list[str] | None = None, size: int = 240) -> str:
    text = " ".join(body.split())
    start = 0
    for term in query_terms or []:
        pos = text.lower().find(term)
        if pos >= 0:
            start = max(0, pos - 60)
            break
    part = text[start : start + size]
    return ("…" if start else "") + part + ("…" if start + size < len(text) else "")


class Memory:
    """Notes with [[wikilinks]]; shared by the settings UI, the agent's memory tools and dreaming."""

    def __init__(self, repo: Repo) -> None:
        self.repo = repo

    @staticmethod
    def view(row: dict[str, Any], full: bool = False) -> dict[str, Any]:
        out = {
            "id": row["id"],
            "title": row["title"],
            "kind": row["kind"],
            "tags": row["tags"] or [],
            "pinned": bool(row["pinned"]),
            "importance": row["importance"],
            "source": row["source"],
            "source_task_id": row["source_task_id"],
            "recall_count": row["recall_count"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "links": wikilinks(row["body"]),
        }
        out["body" if full else "snippet"] = row["body"] if full else snippet(row["body"])
        return out

    async def create(
        self,
        *,
        title: str,
        body: str = "",
        kind: str = "note",
        tags: list[str] | tuple[str, ...] = (),
        pinned: bool = False,
        importance: int = 5,
        source: str = "user",
        task_id: str | None = None,
        link_to: str | None = None,
    ) -> dict[str, Any]:
        title = clean_title(title)
        if await self.repo.get_note_by_title(title):
            raise NoteError(f"a note titled {title!r} already exists")
        if link_to and link_to.strip().lower() != title.lower() and link_to.strip().lower() not in {t.lower() for t in wikilinks(body)}:
            body = f"{body.rstrip()}\n\n[[{clean_title(link_to)}]]".strip()
        note_id = new_id("mem")
        await self.repo.create_note(
            {
                "id": note_id,
                "title": title,
                "body": redact(body)[:BODY_MAX],
                "kind": kind if kind in KINDS else "note",
                "tags": clean_tags(tags),
                "pinned": int(pinned),
                "importance": max(1, min(10, int(importance))),
                "source": source,
                "source_task_id": task_id,
            }
        )
        row = await self.repo.get_note(note_id)
        assert row is not None
        return row

    async def update(self, note_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        row = await self.repo.get_note(note_id)
        if not row:
            raise NoteError("note not found")
        values: dict[str, Any] = {}
        if "title" in fields:
            title = clean_title(fields["title"])
            other = await self.repo.get_note_by_title(title)
            if other and other["id"] != note_id:
                raise NoteError(f"a note titled {title!r} already exists")
            if title != row["title"]:
                values["title"] = title
                await self._rename_links(row["title"], title)
        if "body" in fields:
            values["body"] = redact(str(fields["body"]))[:BODY_MAX]
        if "kind" in fields:
            values["kind"] = fields["kind"] if fields["kind"] in KINDS else "note"
        if "tags" in fields:
            values["tags"] = clean_tags(fields["tags"])
        if "pinned" in fields:
            values["pinned"] = int(bool(fields["pinned"]))
        if "importance" in fields:
            values["importance"] = max(1, min(10, int(fields["importance"])))
        if values:
            await self.repo.update_note(note_id, values)
        updated = await self.repo.get_note(note_id)
        assert updated is not None
        return updated

    async def center(self) -> dict[str, Any] | None:
        note_id = await self.repo.get_setting(CENTER_KEY)
        return await self.repo.get_note(note_id) if note_id else None

    async def ensure_center(self, title: str) -> dict[str, Any]:
        """The note the graph is built around: at first the owner's own note, later any note the owner picks."""
        row = await self.center()
        if row:
            return row
        title = clean_title(title)
        row = await self.repo.get_note_by_title(title) or await self.create(title=title, kind="person", pinned=True, importance=10)
        await self.repo.set_setting(CENTER_KEY, row["id"])
        return row

    async def set_center(self, note_id: str) -> dict[str, Any]:
        row = await self.repo.get_note(note_id)
        if not row:
            raise NoteError("note not found")
        await self.repo.set_setting(CENTER_KEY, note_id)
        return row

    async def attach(self, title: str, body: str) -> str:
        """A new note that links to no known note yet is linked to the central one, so the graph stays in one piece."""
        center = await self.center()
        if not center or center["title"].lower() == title.lower():
            return body
        known = {r["title"].lower() for r in await self.repo.list_notes()} - {title.lower()}
        if any(t.lower() in known for t in wikilinks(body)):
            return body
        return f"{body.rstrip()}\n\n[[{center['title']}]]".strip()

    async def _rename_links(self, old: str, new: str) -> None:
        pattern = re.compile(r"\[\[" + re.escape(old) + r"(\|[^\[\]\n]*)?\]\]", re.I)
        for row in await self.repo.list_notes():
            body = pattern.sub(lambda m: f"[[{new}{m.group(1) or ''}]]", row["body"])
            if body != row["body"]:
                await self.repo.update_note(row["id"], {"body": body})

    async def backlinks(self, title: str) -> list[dict[str, Any]]:
        key = title.lower()
        return [
            {"id": r["id"], "title": r["title"]}
            for r in await self.repo.list_notes()
            if key in (t.lower() for t in wikilinks(r["body"]))
        ]

    async def search(self, query: str, limit: int = 8) -> list[dict[str, Any]]:
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) >= 2]
        scored = []
        for row in await self.repo.list_notes():
            title, body, tags = row["title"].lower(), row["body"].lower(), " ".join(row["tags"] or [])
            score = sum(3 * (t in title) + 2 * (t in tags) + min(body.count(t), 3) for t in terms) if terms else 1
            if score:
                scored.append((score, row["importance"], row["recall_count"], row))
        scored.sort(key=lambda x: x[:3], reverse=True)
        return [r for *_, r in scored[:limit]]

    async def agent_search(self, query: str, limit: int) -> str:
        rows = await self.search(query, limit)
        await self.repo.mark_recalled([r["id"] for r in rows])
        if not rows:
            return f"No memory notes match {query!r}."
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) >= 2]
        return "\n\n".join(
            f"## {r['title']} ({r['kind']}{', #' + ' #'.join(r['tags']) if r['tags'] else ''})\n{snippet(r['body'], terms, 400)}"
            for r in rows
        )

    async def agent_read(self, title: str) -> str:
        row = await self.repo.get_note_by_title(title)
        if not row:
            matches = await self.search(title, 5)
            hint = ", ".join(r["title"] for r in matches) or "none"
            return f"No note titled {title!r}. Closest notes: {hint}."
        await self.repo.mark_recalled([row["id"]])
        back = ", ".join(b["title"] for b in await self.backlinks(row["title"])) or "none"
        return f"# {row['title']} ({row['kind']})\n{row['body']}\n\nLinked from: {back}"

    async def agent_save(self, title: str, content: str, kind: str, tags: list[str], task_id: str) -> str:
        """The agent may add notes or append to existing ones, never overwrite what is already there."""
        row = await self.repo.get_note_by_title(clean_title(title))
        content = redact(content.strip())
        if row:
            if content.lower() in row["body"].lower():
                return f"Note {row['title']!r} already contains this."
            body = (row["body"].rstrip() + "\n\n" + content).strip()
            await self.update(row["id"], {"body": body, "tags": [*(row["tags"] or []), *tags]})
            return f"Appended to note {row['title']!r}."
        note = await self.create(title=title, body=await self.attach(clean_title(title), content), kind=kind, tags=tags, source="agent", task_id=task_id)
        return f"Saved new note {note['title']!r}."

    async def context(self) -> str:
        """Pinned and most important notes for the system prompt, within a fixed character budget."""
        rows = await self.repo.list_notes()
        rows.sort(key=lambda r: (r["pinned"], r["importance"], r["recall_count"]), reverse=True)
        lines: list[str] = []
        used = 0
        for r in rows:
            text = " ".join(r["body"].split())
            if not text:
                continue
            limit = 600 if r["pinned"] else 200
            line = f"- {r['title']}: {text[:limit]}{'…' if len(text) > limit else ''}"
            if used + len(line) > CONTEXT_BUDGET:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    async def graph(self, with_tags: bool) -> dict[str, Any]:
        rows = await self.repo.list_notes()
        by_title = {r["title"].lower(): r["id"] for r in rows}
        nodes: list[dict[str, Any]] = [
            {"id": r["id"], "label": r["title"], "kind": r["kind"], "weight": r["importance"], "pinned": bool(r["pinned"])}
            for r in rows
        ]
        links: list[dict[str, str]] = []
        ghosts: set[str] = set()
        tags: set[str] = set()
        for r in rows:
            for title in wikilinks(r["body"]):
                target = by_title.get(title.lower())
                if target is None:
                    target = f"ghost:{title.lower()}"
                    if target not in ghosts:
                        ghosts.add(target)
                        nodes.append({"id": target, "label": title, "kind": "note", "ghost": True, "weight": 0})
                if target != r["id"]:
                    links.append({"source": r["id"], "target": target})
            if with_tags:
                for tag in r["tags"] or []:
                    if tag not in tags:
                        tags.add(tag)
                        nodes.append({"id": f"tag:{tag}", "label": f"#{tag}", "kind": "tag", "weight": 0})
                    links.append({"source": r["id"], "target": f"tag:{tag}"})
        center = await self.center()
        return {"nodes": nodes, "links": links, "center": center["id"] if center else None}
