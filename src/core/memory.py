import re
from typing import Any

from mensarium.core.repo import Repo
from mensarium.shared.ids import new_id
from mensarium.shared.redaction import redact

KINDS = ("fact", "preference", "project", "person", "device", "howto", "task", "topic", "note")
NOTE_KINDS = tuple(k for k in KINDS if k != "topic")
WIKILINK = re.compile(r"\[\[([^\[\]|#\n]+?)(?:\|[^\[\]\n]*)?\]\]")
BAD_TITLE = re.compile(r"[\[\]|#\n]")
TITLE_MAX = 120
BODY_MAX = 20000
SAVE_MAX = 1500
CONTEXT_BUDGET = 3500
TOPIC_CHARS = 300
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


def first_line(body: str, size: int) -> str:
    text = " ".join(body.split())
    return text[:size] + ("…" if len(text) > size else "")


class Memory:
    """Notes with [[wikilinks]] grouped into topics; shared by the settings UI, the agent's memory tools and dreaming.

    A topic is itself a note (kind "topic") whose body describes the area; every other note may belong to one topic.
    An archived note is kept for the owner but leaves the graph, the prompt and search.
    """

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
            "topic_id": row.get("topic_id"),
            "archived": bool(row.get("archived")),
            "links": wikilinks(row["body"]),
        }
        out["body" if full else "snippet"] = row["body"] if full else snippet(row["body"])
        return out

    async def notes(self, archived: bool = False) -> list[dict[str, Any]]:
        rows = await self.repo.list_notes()
        return rows if archived else [r for r in rows if not r.get("archived")]

    # ---- topics ----

    async def topics(self) -> list[dict[str, Any]]:
        rows = await self.notes()
        counts: dict[str, int] = {}
        for r in rows:
            if r.get("topic_id"):
                counts[r["topic_id"]] = counts.get(r["topic_id"], 0) + 1
        out = [self.view(r) | {"count": counts.get(r["id"], 0), "description": first_line(r["body"], TOPIC_CHARS)} for r in rows if r["kind"] == "topic"]
        out.sort(key=lambda t: t["title"].casefold())
        return out

    async def ensure_topic(self, title: str, body: str = "") -> dict[str, Any]:
        row = await self.repo.get_note_by_title(clean_title(title))
        if row:
            if row["kind"] != "topic":
                raise NoteError(f"{row['title']!r} is a note, not a topic")
            return row
        return await self.create(title=title, body=body, kind="topic", source="dream", importance=6)

    async def _topic_id(self, topic_id: str | None, kind: str) -> str | None:
        if not topic_id:
            return None
        if kind == "topic":
            raise NoteError("a topic can't belong to another topic")
        row = await self.repo.get_note(topic_id)
        if not row or row["kind"] != "topic":
            raise NoteError("topic not found")
        return topic_id

    # ---- notes ----

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
        topic_id: str | None = None,
    ) -> dict[str, Any]:
        title = clean_title(title)
        if await self.repo.get_note_by_title(title):
            raise NoteError(f"a note titled {title!r} already exists")
        if link_to and link_to.strip().lower() != title.lower() and link_to.strip().lower() not in {t.lower() for t in wikilinks(body)}:
            body = f"{body.rstrip()}\n\n[[{clean_title(link_to)}]]".strip()
        kind = kind if kind in KINDS else "note"
        note_id = new_id("mem")
        await self.repo.create_note(
            {
                "id": note_id,
                "title": title,
                "body": redact(body)[:BODY_MAX],
                "kind": kind,
                "tags": clean_tags(tags),
                "pinned": int(pinned),
                "importance": max(1, min(10, int(importance))),
                "source": source,
                "source_task_id": task_id,
                "topic_id": await self._topic_id(topic_id, kind),
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
        kind = row["kind"]
        if "kind" in fields:
            kind = values["kind"] = fields["kind"] if fields["kind"] in KINDS else "note"
        if "topic_id" in fields:
            values["topic_id"] = await self._topic_id(fields["topic_id"] or None, kind)
        elif kind == "topic" and row.get("topic_id"):
            values["topic_id"] = None
        if "tags" in fields:
            values["tags"] = clean_tags(fields["tags"])
        if "pinned" in fields:
            values["pinned"] = int(bool(fields["pinned"]))
        if "importance" in fields:
            values["importance"] = max(1, min(10, int(fields["importance"])))
        if "archived" in fields:
            values["archived"] = int(bool(fields["archived"]))
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
            for r in await self.notes()
            if key in (t.lower() for t in wikilinks(r["body"]))
        ]

    async def ghosts(self) -> dict[str, list[str]]:
        """Titles that notes link to but that have no note: ghost title -> titles of the notes linking to it."""
        rows = await self.notes()
        known = {r["title"].lower() for r in rows}
        out: dict[str, list[str]] = {}
        for r in rows:
            for t in wikilinks(r["body"]):
                if t.lower() not in known:
                    out.setdefault(t, []).append(r["title"])
        return out

    # ---- tidy operations (applied by dreaming or by the owner from a proposal) ----

    async def apply_op(self, op: dict[str, Any]) -> dict[str, Any]:
        """One tidy operation on notes by title. Returns the change for the dream journal."""
        action = op.get("action")
        title = str(op.get("title", "")).strip()
        row = await self.repo.get_note_by_title(title) if title else None
        if action == "resolve_ghost":
            target = await self.repo.get_note_by_title(str(op.get("into", "")))
            if target:
                await self._rename_links(title, target["title"])
                return {"action": "relinked", "id": target["id"], "title": f"{title} → {target['title']}"}
            note = await self.create(title=title, body=str(op.get("body", "")), kind=str(op.get("kind", "fact")), source="dream", topic_id=await self._topic_by_title(op.get("topic")))
            return {"action": "created", "id": note["id"], "title": note["title"]}
        if not row:
            raise NoteError(f"note {title!r} not found")
        if action == "merge":
            body = str(op.get("body") or row["body"])
            tags = list(row["tags"] or [])
            for other_title in op.get("from", []):
                other = await self.repo.get_note_by_title(str(other_title))
                if not other or other["id"] == row["id"]:
                    continue
                tags += other["tags"] or []
                await self._rename_links(other["title"], row["title"])
                await self.repo.delete_note(other["id"])
            await self.update(row["id"], {"body": body, "tags": tags, "importance": max(row["importance"], int(op.get("importance") or 0))})
            return {"action": "merged", "id": row["id"], "title": row["title"]}
        if action == "rewrite":
            await self.update(row["id"], {"body": str(op.get("body", "")), **({"title": op["new_title"]} if op.get("new_title") else {})})
            return {"action": "updated", "id": row["id"], "title": row["title"]}
        if action == "retire":
            await self.update(row["id"], {"archived": True, "pinned": False})
            return {"action": "retired", "id": row["id"], "title": row["title"]}
        if action == "retopic":
            await self.update(row["id"], {"topic_id": await self._topic_by_title(op.get("topic"), create=True)})
            return {"action": "moved", "id": row["id"], "title": row["title"]}
        if action == "rekind":
            await self.update(row["id"], {"kind": str(op.get("kind", row["kind"]))})
            return {"action": "updated", "id": row["id"], "title": row["title"]}
        if action == "importance":
            await self.update(row["id"], {"importance": int(op.get("importance", row["importance"]))})
            return {"action": "updated", "id": row["id"], "title": row["title"]}
        raise NoteError(f"unknown tidy action {action!r}")

    async def _topic_by_title(self, title: Any, create: bool = False) -> str | None:
        """A topic by title. With create, a missing topic is made, and a plain note carrying that title becomes the
        topic itself (its text turns into the description), since a project note and its topic are one thing."""
        if not title:
            return None
        row = await self.repo.get_note_by_title(str(title))
        if row and row["kind"] == "topic":
            return row["id"]
        if not create:
            return None
        if not row:
            return (await self.ensure_topic(str(title)))["id"]
        center = await self.center()
        if center and center["id"] == row["id"]:
            raise NoteError("the central note can't become a topic")
        await self.update(row["id"], {"kind": "topic", "topic_id": None})
        return row["id"]

    # ---- agent tools ----

    async def search(self, query: str, limit: int = 8, topic: str | None = None) -> list[dict[str, Any]]:
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) >= 2]
        topic_id = await self._topic_by_title(topic) if topic else None
        scored = []
        for row in await self.notes():
            if topic_id and row.get("topic_id") != topic_id and row["id"] != topic_id:
                continue
            title, body, tags = row["title"].lower(), row["body"].lower(), " ".join(row["tags"] or [])
            score = sum(3 * (t in title) + 2 * (t in tags) + min(body.count(t), 3) for t in terms) if terms else 1
            if score:
                scored.append((score, row["importance"], row["recall_count"], row))
        scored.sort(key=lambda x: x[:3], reverse=True)
        return [r for *_, r in scored[:limit]]

    async def agent_search(self, query: str, limit: int, topic: str | None = None) -> str:
        rows = await self.search(query, limit, topic)
        await self.repo.mark_recalled([r["id"] for r in rows])
        if not rows:
            return f"No memory notes match {query!r}."
        names = {t["id"]: t["title"] for t in await self.topics()}
        terms = [t for t in re.findall(r"\w+", query.lower()) if len(t) >= 2]
        return "\n\n".join(
            f"## {r['title']} ({r['kind']}{', topic ' + names[r['topic_id']] if r.get('topic_id') in names else ''}"
            f"{', #' + ' #'.join(r['tags']) if r['tags'] else ''})\n{snippet(r['body'], terms, 400)}"
            for r in rows
        )

    async def agent_read(self, title: str) -> str:
        row = await self.repo.get_note_by_title(title)
        if not row:
            matches = await self.search(title, 5)
            hint = ", ".join(r["title"] for r in matches) or "none"
            return f"No note titled {title!r}. Closest notes: {hint}."
        await self.repo.mark_recalled([row["id"]])
        if row["kind"] == "topic":
            members = [r for r in await self.notes() if r.get("topic_id") == row["id"]]
            listing = "\n".join(f"- {r['title']} ({r['kind']}): {first_line(r['body'], 160)}" for r in members) or "(no notes yet)"
            return f"# {row['title']} (topic)\n{row['body']}\n\nNotes in this topic:\n{listing}"
        back = ", ".join(b["title"] for b in await self.backlinks(row["title"])) or "none"
        return f"# {row['title']} ({row['kind']})\n{row['body']}\n\nLinked from: {back}"

    async def agent_save(self, title: str, content: str, kind: str, tags: list[str], task_id: str, topic: str | None = None) -> str:
        """The agent may add notes or append to existing ones, never overwrite what is already there."""
        content = redact(content.strip())
        if len(content) > SAVE_MAX:
            return f"Too long ({len(content)} characters): memory keeps knowledge, not reports. Shorten it to {SAVE_MAX} characters or less."
        row = await self.repo.get_note_by_title(clean_title(title))
        topic_id = await self._topic_by_title(topic, create=True)
        if row:
            if content.lower() in row["body"].lower():
                return f"Note {row['title']!r} already contains this."
            body = (row["body"].rstrip() + "\n\n" + content).strip()
            fields: dict[str, Any] = {"body": body, "tags": [*(row["tags"] or []), *tags]}
            if topic_id and not row.get("topic_id") and row["kind"] != "topic":
                fields["topic_id"] = topic_id
            await self.update(row["id"], fields)
            return f"Appended to note {row['title']!r}."
        note = await self.create(title=title, body=content, kind=kind if kind in NOTE_KINDS else "fact", tags=tags, source="agent", task_id=task_id, topic_id=topic_id)
        return f"Saved new note {note['title']!r}."

    async def context(self) -> str:
        """Topics first, then pinned and most important notes, within a fixed character budget."""
        rows = await self.notes()
        topics = sorted((r for r in rows if r["kind"] == "topic"), key=lambda r: r["title"].casefold())
        rest = sorted((r for r in rows if r["kind"] != "topic"), key=lambda r: (r["pinned"], r["importance"], r["recall_count"]), reverse=True)
        lines: list[str] = []
        used = 0
        for r in [*topics, *rest]:
            text = " ".join(r["body"].split())
            if not text:
                continue
            limit = TOPIC_CHARS if r["kind"] == "topic" else 600 if r["pinned"] else 120 if r["kind"] == "task" else 200
            line = f"- {'[topic] ' if r['kind'] == 'topic' else ''}{r['title']}: {text[:limit]}{'…' if len(text) > limit else ''}"
            if used + len(line) > CONTEXT_BUDGET:
                break
            lines.append(line)
            used += len(line)
        return "\n".join(lines)

    async def graph(self, with_tags: bool) -> dict[str, Any]:
        rows = await self.notes()
        by_title = {r["title"].lower(): r["id"] for r in rows}
        nodes: list[dict[str, Any]] = [
            {"id": r["id"], "label": r["title"], "kind": r["kind"], "weight": r["importance"], "pinned": bool(r["pinned"]), "topic": r.get("topic_id")}
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
                        nodes.append({"id": target, "label": title, "kind": "note", "ghost": True, "weight": 0, "topic": r.get("topic_id")})
                if target != r["id"]:
                    links.append({"source": r["id"], "target": target})
            if with_tags:
                for tag in r["tags"] or []:
                    if tag not in tags:
                        tags.add(tag)
                        nodes.append({"id": f"tag:{tag}", "label": f"#{tag}", "kind": "tag", "weight": 0})
                    links.append({"source": r["id"], "target": f"tag:{tag}"})
        center = await self.center()
        return {"nodes": nodes, "links": links, "center": center["id"] if center else None, "topics": await self.topics()}
