import json
from pathlib import Path
from typing import Any

import aiosqlite

SCHEMA_VERSION = 14

COLUMN_MIGRATIONS = [
    ("memory_notes", "topic_id", "TEXT"),
    ("memory_notes", "archived", "INTEGER NOT NULL DEFAULT 0"),
    ("dream_runs", "proposals", "TEXT NOT NULL DEFAULT '[]'"),
    ("automations", "state", "TEXT NOT NULL DEFAULT '{}'"),
    ("tasks", "mode", "TEXT NOT NULL DEFAULT 'ask'"),
    ("tasks", "model", "TEXT"),
    ("targets", "disabled_tools", "TEXT NOT NULL DEFAULT '[]'"),
    ("plugins", "config", "TEXT NOT NULL DEFAULT '{}'"),
    ("plugins", "status", "TEXT NOT NULL DEFAULT '{}'"),
    ("tasks", "parent_id", "TEXT"),
    ("tasks", "label", "TEXT"),
    ("tasks", "plan", "TEXT NOT NULL DEFAULT '[]'"),
    ("tasks", "automation_id", "TEXT"),
    ("tasks", "project_id", "TEXT"),
    ("projects", "git_url", "TEXT"),
    ("tasks", "branch", "TEXT"),
    ("tasks", "base_ref", "TEXT"),
    ("tasks", "base_sha", "TEXT"),
    ("tasks", "head_sha", "TEXT"),
    ("tasks", "archived_at", "TEXT"),
    ("tasks", "provider", "TEXT"),
    ("automations", "provider", "TEXT"),
    ("projects", "instructions", "TEXT"),
    ("tasks", "diff_stat", "TEXT"),
    ("projects", "main_branch", "TEXT"),
    ("project_deliveries", "branch", "TEXT"),
    ("projects", "checks", "TEXT"),
    ("tasks", "checks", "TEXT"),
    ("tool_calls", "undo", "TEXT"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, settings TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS targets (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL, platform TEXT NOT NULL,
    hostname TEXT NOT NULL, status TEXT NOT NULL, public_key TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '{}', policy TEXT NOT NULL DEFAULT '{}', agent_version TEXT,
    last_seen_at TEXT, created_at TEXT NOT NULL, revoked_at TEXT, disabled_tools TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS target_pairings (
    id TEXT PRIMARY KEY, token_hash TEXT NOT NULL UNIQUE, target_id TEXT, expires_at TEXT NOT NULL,
    used_at TEXT, revoked_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_profiles (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL, version TEXT NOT NULL,
    body TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, profile_id TEXT NOT NULL, target_id TEXT NOT NULL,
    input TEXT NOT NULL, status TEXT NOT NULL, status_reason TEXT, result TEXT, mode TEXT NOT NULL DEFAULT 'ask', model TEXT,
    budget TEXT NOT NULL DEFAULT '{}', policy_snapshot_hash TEXT, trace_id TEXT NOT NULL,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, parent_id TEXT, label TEXT, plan TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS task_steps (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, sequence INTEGER NOT NULL, kind TEXT NOT NULL,
    input TEXT NOT NULL DEFAULT '{}', output TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL,
    latency_ms INTEGER, provider TEXT, model_id TEXT, params TEXT, usage TEXT, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS task_steps_task ON task_steps(task_id, sequence);
CREATE TABLE IF NOT EXISTS tool_calls (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, task_step_id TEXT NOT NULL, tool_name TEXT NOT NULL,
    arguments TEXT NOT NULL, risk TEXT NOT NULL, display TEXT NOT NULL, status TEXT NOT NULL,
    result_ref TEXT, request_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS approvals (
    id TEXT PRIMARY KEY, tool_call_id TEXT NOT NULL, task_id TEXT NOT NULL, requested_at TEXT NOT NULL,
    expires_at TEXT NOT NULL, decision TEXT, approved_by TEXT, decided_at TEXT, note TEXT, used_at TEXT
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, task_id TEXT, kind TEXT NOT NULL, uri TEXT NOT NULL,
    sha256 TEXT NOT NULL, size INTEGER NOT NULL, metadata TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, actor TEXT NOT NULL, event_type TEXT NOT NULL,
    payload TEXT NOT NULL, created_at TEXT NOT NULL, prev_hash TEXT NOT NULL, hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS task_events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, event TEXT NOT NULL,
    payload TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS task_events_task ON task_events(task_id, seq);
CREATE TABLE IF NOT EXISTS memory_notes (
    id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'note',
    tags TEXT NOT NULL DEFAULT '[]', pinned INTEGER NOT NULL DEFAULT 0, importance INTEGER NOT NULL DEFAULT 5,
    source TEXT NOT NULL DEFAULT 'user', source_task_id TEXT, recall_count INTEGER NOT NULL DEFAULT 0,
    last_recalled_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, topic_id TEXT,
    archived INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS dream_runs (
    id TEXT PRIMARY KEY, trigger TEXT NOT NULL, status TEXT NOT NULL, phase TEXT, model TEXT,
    started_at TEXT NOT NULL, finished_at TEXT, stats TEXT NOT NULL DEFAULT '{}',
    changes TEXT NOT NULL DEFAULT '[]', diary TEXT, error TEXT, proposals TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE IF NOT EXISTS plugins (
    id TEXT PRIMARY KEY, version TEXT NOT NULL, source TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1,
    manifest TEXT NOT NULL, config TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT '{}',
    installed_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS automations (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL, prompt TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1, schedule TEXT NOT NULL, target_id TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'ask', model TEXT, timeout_s INTEGER NOT NULL DEFAULT 3600,
    notify INTEGER NOT NULL DEFAULT 1, delete_after_run INTEGER NOT NULL DEFAULT 0,
    created_by TEXT NOT NULL DEFAULT 'user', next_run_at TEXT, last_run_at TEXT, last_status TEXT, last_error TEXT,
    failures INTEGER NOT NULL DEFAULT 0, disabled_reason TEXT, running_run_id TEXT,
    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, state TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS automation_runs (
    id TEXT PRIMARY KEY, automation_id TEXT NOT NULL, task_id TEXT, trigger TEXT NOT NULL, status TEXT NOT NULL,
    result TEXT, error TEXT, started_at TEXT NOT NULL, finished_at TEXT, duration_ms INTEGER
);
CREATE INDEX IF NOT EXISTS automation_runs_auto ON automation_runs(automation_id, started_at);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
    source_target_id TEXT NOT NULL, source_path TEXT NOT NULL, default_executor_id TEXT, default_base TEXT NOT NULL DEFAULT 'snapshot',
    include_remotes INTEGER NOT NULL DEFAULT 1, fetch_origin INTEGER NOT NULL DEFAULT 0,
    size_limit_mb INTEGER NOT NULL DEFAULT 1024, file_limit_mb INTEGER NOT NULL DEFAULT 100,
    head_sha TEXT, snapshot_sha TEXT, default_branch TEXT, last_sync_at TEXT, size_bytes INTEGER NOT NULL DEFAULT 0,
    skipped TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS projects_source ON projects(source_target_id, source_path);
CREATE TABLE IF NOT EXISTS project_devices (
    project_id TEXT NOT NULL, target_id TEXT NOT NULL, role TEXT NOT NULL,
    known_refs TEXT NOT NULL DEFAULT '{}', device_refs TEXT NOT NULL DEFAULT '{}', last_sync_at TEXT, last_error TEXT,
    PRIMARY KEY (project_id, target_id)
);
CREATE TABLE IF NOT EXISTS project_deliveries (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, target_id TEXT NOT NULL, task_id TEXT NOT NULL, kind TEXT NOT NULL,
    status TEXT NOT NULL, error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS project_deliveries_target ON project_deliveries(target_id, status);
"""

JSON_COLUMNS = {
    "settings", "capabilities", "policy", "body", "budget", "input", "output", "params", "usage",
    "arguments", "metadata", "payload", "disabled_tools", "manifest", "tags", "stats", "changes", "proposals", "config", "status", "plan",
    "schedule", "skipped", "diff_stat", "state", "checks",
}


def _row(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for k, v in out.items():
        if k in JSON_COLUMNS and isinstance(v, str) and v[:1] in ("{", "["):
            try:
                out[k] = json.loads(v)
            except json.JSONDecodeError:
                pass
    return out


def _dump(value: Any) -> Any:
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        assert self._conn is not None, "database is not connected"
        return self._conn

    async def connect(self) -> None:
        self._conn = await aiosqlite.connect(self.path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        async with self._conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cur:
            tables = {row[0] for row in await cur.fetchall()}
        if "extensions" in tables and "plugins" not in tables:
            await self._conn.execute("ALTER TABLE extensions RENAME TO plugins")
        await self._conn.executescript(SCHEMA)
        for table, column, ddl in COLUMN_MIGRATIONS:
            async with self._conn.execute(f"PRAGMA table_info({table})") as cur:
                if column not in {row[1] for row in await cur.fetchall()}:
                    await self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        await self._conn.execute(
            "INSERT OR REPLACE INTO kv(key, value) VALUES ('schema_version', ?)", (str(SCHEMA_VERSION),)
        )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def insert(self, table: str, values: dict[str, Any]) -> None:
        cols = ", ".join(values)
        marks = ", ".join("?" for _ in values)
        await self.conn.execute(
            f"INSERT INTO {table} ({cols}) VALUES ({marks})", [_dump(v) for v in values.values()]
        )
        await self.conn.commit()

    async def update(self, table: str, row_id: str, values: dict[str, Any], key: str = "id") -> None:
        sets = ", ".join(f"{k} = ?" for k in values)
        await self.conn.execute(
            f"UPDATE {table} SET {sets} WHERE {key} = ?", [*(_dump(v) for v in values.values()), row_id]
        )
        await self.conn.commit()

    async def fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        async with self.conn.execute(sql, params) as cur:
            return _row(await cur.fetchone())

    async def fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        async with self.conn.execute(sql, params) as cur:
            return [r for r in (_row(x) for x in await cur.fetchall()) if r is not None]

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        cur = await self.conn.execute(sql, params)
        await self.conn.commit()
        return cur.lastrowid or 0
