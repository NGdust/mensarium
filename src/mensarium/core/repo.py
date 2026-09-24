from typing import Any

from mensarium.core.db import Database
from mensarium.shared.crypto import canonical_json, sha256_hex
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import now_iso

TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "FAILED_RECOVERABLE", "CANCELED", "PAUSED"}


class Repo:
    def __init__(self, db: Database) -> None:
        self.db = db

    # workspace
    async def get_or_create_workspace(self) -> str:
        row = await self.db.fetchone("SELECT id FROM workspaces ORDER BY created_at LIMIT 1")
        if row:
            return str(row["id"])
        ws_id = new_id("ws")
        await self.db.insert("workspaces", {"id": ws_id, "name": "default", "created_at": now_iso()})
        return ws_id

    # targets
    async def create_target(self, values: dict[str, Any]) -> None:
        await self.db.insert("targets", values)

    async def get_target(self, target_id: str) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM targets WHERE id = ?", (target_id,))

    async def list_targets(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM targets ORDER BY created_at DESC")

    async def update_target(self, target_id: str, values: dict[str, Any]) -> None:
        await self.db.update("targets", target_id, values)

    # pairing
    async def create_pairing(self, token_hash: str, expires_at: str) -> str:
        pid = new_id("pair")
        await self.db.insert(
            "target_pairings",
            {"id": pid, "token_hash": token_hash, "expires_at": expires_at, "created_at": now_iso()},
        )
        return pid

    async def get_pairing(self, token_hash: str) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM target_pairings WHERE token_hash = ?", (token_hash,))

    async def use_pairing(self, pairing_id: str, target_id: str) -> bool:
        cur = await self.db.conn.execute(
            "UPDATE target_pairings SET used_at = ?, target_id = ? WHERE id = ? AND used_at IS NULL",
            (now_iso(), target_id, pairing_id),
        )
        await self.db.conn.commit()
        return cur.rowcount == 1

    # profiles
    async def upsert_profile(self, workspace_id: str, profile: dict[str, Any]) -> None:
        now = now_iso()
        existing = await self.get_profile(profile["id"])
        if existing:
            await self.db.update(
                "agent_profiles",
                profile["id"],
                {"name": profile["name"], "version": profile["version"], "body": profile, "updated_at": now},
            )
        else:
            await self.db.insert(
                "agent_profiles",
                {
                    "id": profile["id"],
                    "workspace_id": workspace_id,
                    "name": profile["name"],
                    "version": profile["version"],
                    "body": profile,
                    "created_at": now,
                    "updated_at": now,
                },
            )

    async def get_profile(self, profile_id: str) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM agent_profiles WHERE id = ?", (profile_id,))

    async def list_profiles(self) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM agent_profiles ORDER BY name")

    # tasks
    async def create_task(self, values: dict[str, Any]) -> None:
        await self.db.insert("tasks", values)

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        return await self.db.fetchone(
            "SELECT t.*, g.name AS target_name FROM tasks t LEFT JOIN targets g ON g.id = t.target_id WHERE t.id = ?",
            (task_id,),
        )

    async def list_tasks(self, limit: int = 100) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT t.*, g.name AS target_name FROM tasks t LEFT JOIN targets g ON g.id = t.target_id "
            "ORDER BY t.updated_at DESC LIMIT ?",
            (limit,),
        )

    async def update_task(self, task_id: str, values: dict[str, Any]) -> None:
        await self.db.update("tasks", task_id, {**values, "updated_at": now_iso()})

    async def list_active_tasks(self) -> list[dict[str, Any]]:
        marks = ",".join("?" for _ in TERMINAL_STATUSES)
        return await self.db.fetchall(
            f"SELECT * FROM tasks WHERE status NOT IN ({marks})", tuple(TERMINAL_STATUSES)
        )

    async def delete_task(self, task_id: str) -> list[str]:
        artifacts = await self.db.fetchall("SELECT id FROM artifacts WHERE task_id = ?", (task_id,))
        for table in ("task_events", "task_steps", "tool_calls", "approvals", "artifacts"):
            await self.db.conn.execute(f"DELETE FROM {table} WHERE task_id = ?", (task_id,))
        await self.db.conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        await self.db.conn.commit()
        return [str(a["id"]) for a in artifacts]

    # steps
    async def add_step(self, task_id: str, kind: str, values: dict[str, Any]) -> str:
        row = await self.db.fetchone(
            "SELECT COALESCE(MAX(sequence), 0) AS s FROM task_steps WHERE task_id = ?", (task_id,)
        )
        step_id = new_id("step")
        await self.db.insert(
            "task_steps",
            {
                "id": step_id,
                "task_id": task_id,
                "sequence": (row["s"] if row else 0) + 1,
                "kind": kind,
                "status": "done",
                "created_at": now_iso(),
                **values,
            },
        )
        return step_id

    async def list_steps(self, task_id: str) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM task_steps WHERE task_id = ? ORDER BY sequence", (task_id,))

    async def count_steps(self, task_id: str, kind: str) -> int:
        row = await self.db.fetchone(
            "SELECT COUNT(*) AS c FROM task_steps WHERE task_id = ? AND kind = ?", (task_id, kind)
        )
        return int(row["c"]) if row else 0

    # tool calls & approvals
    async def create_tool_call(self, values: dict[str, Any]) -> None:
        now = now_iso()
        await self.db.insert("tool_calls", {**values, "created_at": now, "updated_at": now})

    async def update_tool_call(self, tc_id: str, values: dict[str, Any]) -> None:
        await self.db.update("tool_calls", tc_id, {**values, "updated_at": now_iso()})

    async def get_tool_call(self, tc_id: str) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM tool_calls WHERE id = ?", (tc_id,))

    async def create_approval(self, values: dict[str, Any]) -> None:
        await self.db.insert("approvals", values)

    async def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM approvals WHERE id = ?", (approval_id,))

    async def decide_approval(self, approval_id: str, decision: str, actor: str, note: str | None) -> bool:
        cur = await self.db.conn.execute(
            "UPDATE approvals SET decision = ?, approved_by = ?, decided_at = ?, note = ? "
            "WHERE id = ? AND decision IS NULL",
            (decision, actor, now_iso(), note, approval_id),
        )
        await self.db.conn.commit()
        return cur.rowcount == 1

    async def consume_approval(self, approval_id: str) -> bool:
        cur = await self.db.conn.execute(
            "UPDATE approvals SET used_at = ? WHERE id = ? AND decision = 'approved' AND used_at IS NULL",
            (now_iso(), approval_id),
        )
        await self.db.conn.commit()
        return cur.rowcount == 1

    async def expire_open_approvals(self, task_id: str | None = None) -> None:
        sql = "UPDATE approvals SET decision = 'expired', decided_at = ? WHERE decision IS NULL"
        params: tuple[Any, ...] = (now_iso(),)
        if task_id:
            sql += " AND task_id = ?"
            params += (task_id,)
        await self.db.execute(sql, params)

    # artifacts
    async def create_artifact(self, values: dict[str, Any]) -> None:
        await self.db.insert("artifacts", {**values, "created_at": now_iso()})

    async def get_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM artifacts WHERE id = ?", (artifact_id,))

    # extensions
    async def list_extensions(self, enabled_only: bool = False) -> list[dict[str, Any]]:
        where = " WHERE enabled = 1" if enabled_only else ""
        return await self.db.fetchall(f"SELECT * FROM extensions{where} ORDER BY id")

    async def get_extension(self, ext_id: str) -> dict[str, Any] | None:
        return await self.db.fetchone("SELECT * FROM extensions WHERE id = ?", (ext_id,))

    async def save_extension(self, manifest: dict[str, Any], source: str) -> None:
        now = now_iso()
        await self.db.execute(
            "INSERT INTO extensions(id, version, source, enabled, manifest, installed_at, updated_at) "
            "VALUES (?, ?, ?, 1, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET version = excluded.version, "
            "source = excluded.source, manifest = excluded.manifest, updated_at = excluded.updated_at",
            (manifest["id"], manifest["version"], source, canonical_json(manifest).decode(), now, now),
        )

    async def set_extension_enabled(self, ext_id: str, enabled: bool) -> None:
        await self.db.update("extensions", ext_id, {"enabled": int(enabled), "updated_at": now_iso()})

    async def delete_extension(self, ext_id: str) -> None:
        await self.db.execute("DELETE FROM extensions WHERE id = ?", (ext_id,))

    # events
    async def add_event(self, task_id: str, event: str, payload: dict[str, Any]) -> dict[str, Any]:
        created = now_iso()
        seq = await self.db.execute(
            "INSERT INTO task_events(task_id, event, payload, created_at) VALUES (?, ?, ?, ?)",
            (task_id, event, canonical_json(payload).decode(), created),
        )
        return {"seq": seq, "event": event, "task_id": task_id, "payload": payload, "created_at": created}

    async def list_events(self, task_id: str, after: int = 0) -> list[dict[str, Any]]:
        return await self.db.fetchall(
            "SELECT * FROM task_events WHERE task_id = ? AND seq > ? ORDER BY seq", (task_id, after)
        )

    # audit (hash chain)
    async def audit(self, workspace_id: str, actor: str, event_type: str, payload: dict[str, Any]) -> None:
        last = await self.db.fetchone("SELECT hash FROM audit_events ORDER BY rowid DESC LIMIT 1")
        prev = last["hash"] if last else "sha256:genesis"
        created = now_iso()
        body = {"actor": actor, "event_type": event_type, "payload": payload, "created_at": created, "prev": prev}
        await self.db.insert(
            "audit_events",
            {
                "id": new_id("aud"),
                "workspace_id": workspace_id,
                "actor": actor,
                "event_type": event_type,
                "payload": payload,
                "created_at": created,
                "prev_hash": prev,
                "hash": sha256_hex(canonical_json(body)),
            },
        )

    async def list_audit(self, limit: int = 200) -> list[dict[str, Any]]:
        return await self.db.fetchall("SELECT * FROM audit_events ORDER BY rowid DESC LIMIT ?", (limit,))
