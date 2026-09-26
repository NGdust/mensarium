import asyncio
import contextlib
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from mensarium.contracts.automations import (
    AutomationCreate,
    AutomationError,
    AutomationPatch,
    RunStatus,
    RunTrigger,
    Schedule,
)
from mensarium.core.channels import ChannelManager
from mensarium.core.orchestrator import Orchestrator, TaskError
from mensarium.core.repo import TERMINAL_STATUSES, Repo
from mensarium.shared.cron import CronError, next_after, parse
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import iso, iso_in, now_iso, parse_iso, utcnow

log = logging.getLogger(__name__)

PROFILE = "coding-agent-v1"
TICK_S = 15
POLL_S = 2
MAX_PARALLEL = 3
BACKOFF_S = (30, 60, 300, 900, 3600)
MAX_FAILURES = 10
KEEP_RUNS = 200
KEEP_DAYS = 7
CATCHUP_AFTER_S = 120
NO_REPLY = "NO_REPLY"
UPDATE_EVERY_S = 2 * 3600
UPDATE_SEEDED_KEY = "automations.update_seeded"
UPDATE_PROMPT = (
    "Keep the Mensarium client on this device up to date. Call device.update once: it compares the client version "
    "with the Core version and starts the update when the client is behind. Then finish. Answer with one short line "
    "when an update was started. Answer NO_REPLY when the client is already up to date, the device is offline or "
    "it does not allow remote updates. Do not use any other tool."
)


def update_automation(target: dict[str, Any]) -> AutomationCreate:
    """The automation every paired device gets: check the client version every two hours and update it."""
    return AutomationCreate(
        name=f"Update client on {target['name']}",
        prompt=UPDATE_PROMPT,
        schedule=Schedule.model_validate({"kind": "every", "every_s": UPDATE_EVERY_S, "tz": "UTC"}),
        target_id=target["id"],
        timeout_s=600,
    )


def next_run(schedule: Schedule, after: datetime) -> datetime | None:
    if schedule.kind == "every":
        assert schedule.every_s is not None
        return after + timedelta(seconds=schedule.every_s)
    if schedule.kind == "cron":
        assert schedule.expr is not None
        try:
            spec = parse(schedule.expr)
            nxt = next_after(spec, after.astimezone(ZoneInfo(schedule.tz)))
            while nxt.astimezone(UTC) <= after:
                nxt = next_after(spec, nxt)
        except CronError:
            return None
        return nxt.astimezone(UTC)
    assert schedule.at is not None
    at = parse_iso(schedule.at).astimezone(UTC)
    return at if at > after else None


def first_run(schedule: Schedule) -> str:
    nxt = next_run(schedule, utcnow())
    if nxt is None:
        raise AutomationError("the time is in the past" if schedule.kind == "at" else "the schedule never fires")
    return iso(nxt)


def _next_values(schedule: Schedule) -> dict[str, Any]:
    if nxt := next_run(schedule, utcnow()):
        return {"next_run_at": iso(nxt)}
    reason = "one-shot-done" if schedule.kind == "at" else "never-fires"
    return {"enabled": False, "disabled_reason": reason, "next_run_at": None}


def _after_run(
    row: dict[str, Any], schedule: Schedule, status: RunStatus, failures: int, trigger: RunTrigger
) -> dict[str, Any] | None:
    once = schedule.kind == "at"
    early = once and trigger == "manual" and parse_iso(schedule.at or "") > utcnow()
    done = status == "ok" and once and not early
    if done and row["delete_after_run"]:
        return None
    if not row["enabled"]:
        return {"next_run_at": None}
    if done:
        return {"enabled": False, "disabled_reason": "one-shot-done", "next_run_at": None}
    if early:
        return {}
    if status == "ok":
        return _next_values(schedule)
    if failures >= MAX_FAILURES:
        return {"enabled": False, "disabled_reason": "consecutive-failures", "next_run_at": None}
    return {"next_run_at": iso_in(BACKOFF_S[min(failures - 1, len(BACKOFF_S) - 1)])}


class AutomationManager:
    def __init__(
        self,
        repo: Repo,
        workspace_id: str,
        orchestrator: Orchestrator,
        channels: ChannelManager,
        public_url: str,
    ) -> None:
        self.repo = repo
        self.workspace_id = workspace_id
        self.orchestrator = orchestrator
        self.channels = channels
        self.public_url = public_url
        self.loop: asyncio.Task[None] | None = None
        self.running: dict[str, asyncio.Task[None]] = {}
        self.lock = asyncio.Lock()

    # ---- lifecycle ----------------------------------------------------------

    async def start(self) -> None:
        lost: set[str] = set()
        for run in await self.repo.running_runs():
            await self.repo.update_run(run["id"], {"status": "lost", "error": "core restarted", "finished_at": now_iso()})
            lost.add(run["automation_id"])
        for row in await self.repo.list_automations():
            values: dict[str, Any] = {"running_run_id": None} if row["running_run_id"] else {}
            if row["id"] in lost:
                values |= {"last_status": "lost", "last_error": "core restarted"}
            if row["enabled"] and row["next_run_at"] is None:
                values |= _next_values(Schedule.model_validate(row["schedule"]))
            if values:
                await self.repo.update_automation(row["id"], values)
        await self._seed_update_automations()
        self.loop = asyncio.create_task(self._loop())

    async def _seed_update_automations(self) -> None:
        """Once: give the devices paired before default automations existed their update automation."""
        if await self.repo.get_setting(UPDATE_SEEDED_KEY):
            return
        covered = {row["target_id"] for row in await self.repo.list_automations() if row["created_by"] == "core"}
        for target in await self.repo.list_targets():
            if target["status"] != "revoked" and target["id"] not in covered:
                await self.add_device(target)
        await self.repo.set_setting(UPDATE_SEEDED_KEY, True)

    async def stop(self) -> None:
        tasks = [t for t in (self.loop, *self.running.values()) if t]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.loop = None
        self.running.clear()

    async def _loop(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            try:
                async with self.lock:
                    for row in await self.repo.due_automations(now_iso()):
                        if len(self.running) >= MAX_PARALLEL:
                            break
                        late = utcnow() - parse_iso(row["next_run_at"]) > timedelta(seconds=CATCHUP_AFTER_S)
                        await self._launch(row, "catchup" if late else "schedule")
            except Exception:
                log.exception("automation scheduler failed")

    # ---- views --------------------------------------------------------------

    def view(self, row: dict[str, Any]) -> dict[str, Any]:
        return row | {
            "enabled": bool(row["enabled"]),
            "notify": bool(row["notify"]),
            "delete_after_run": bool(row["delete_after_run"]),
            "schedule_text": Schedule.model_validate(row["schedule"]).text(),
            "running": row["running_run_id"] is not None,
        }

    def preview(self, schedule: Schedule, count: int = 3) -> list[str]:
        out: list[str] = []
        after = utcnow()
        while len(out) < count and (nxt := next_run(schedule, after)):
            out.append(iso(nxt))
            after = nxt
        return out

    async def runs(self, automation_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return await self.repo.list_runs(automation_id, limit)

    async def all(self) -> list[dict[str, Any]]:
        return [self.view(row) for row in await self.repo.list_automations()]

    async def get(self, automation_id: str) -> dict[str, Any]:
        return self.view(await self._row(automation_id))

    async def _row(self, automation_id: str) -> dict[str, Any]:
        row = await self.repo.get_automation(automation_id)
        if not row:
            raise AutomationError("automation not found", 404)
        return row

    # ---- changes ------------------------------------------------------------

    async def create(self, body: AutomationCreate, created_by: str = "user") -> dict[str, Any]:
        await self._check_target(body.target_id)
        next_run_at = first_run(body.schedule)
        automation_id = new_id("auto")
        now = now_iso()
        await self.repo.create_automation(
            {
                "id": automation_id,
                "workspace_id": self.workspace_id,
                **body.model_dump(),
                "created_by": created_by,
                "next_run_at": next_run_at if body.enabled else None,
                "created_at": now,
                "updated_at": now,
            }
        )
        await self.repo.audit(
            self.workspace_id, created_by, "automation.created", {"automation_id": automation_id, "name": body.name}
        )
        return await self.get(automation_id)

    async def add_device(self, target: dict[str, Any]) -> dict[str, Any]:
        return await self.create(update_automation(target), created_by="core")

    async def update(self, automation_id: str, patch: AutomationPatch) -> dict[str, Any]:
        row = await self._row(automation_id)
        values = {k: v for k, v in patch.model_dump(exclude_unset=True).items() if v is not None or k == "model"}
        if "target_id" in values:
            await self._check_target(values["target_id"])
        schedule = Schedule.model_validate(values.get("schedule", row["schedule"]))
        enabled = values.get("enabled", bool(row["enabled"]))
        if enabled != bool(row["enabled"]):
            values |= self._toggle(schedule, enabled)
        elif enabled and "schedule" in values:
            values["next_run_at"] = first_run(schedule)
        await self.repo.update_automation(automation_id, values)
        await self.repo.audit(
            self.workspace_id, "user", "automation.updated", {"automation_id": automation_id, "fields": sorted(values)}
        )
        return await self.get(automation_id)

    async def set_enabled(self, automation_id: str, enabled: bool) -> dict[str, Any]:
        row = await self._row(automation_id)
        values = self._toggle(Schedule.model_validate(row["schedule"]), enabled)
        await self.repo.update_automation(automation_id, values)
        await self.repo.audit(
            self.workspace_id, "user", "automation.updated", {"automation_id": automation_id, "enabled": enabled}
        )
        return await self.get(automation_id)

    async def delete(self, automation_id: str, actor: str = "user") -> None:
        async with self.lock:
            row = await self._row(automation_id)
            run = await self.repo.get_run(row["running_run_id"]) if row["running_run_id"] else None
            if run and run["task_id"]:
                with contextlib.suppress(TaskError):
                    await self.orchestrator.cancel(run["task_id"])
            if task := self.running.pop(automation_id, None):
                task.cancel()
            await self._drop(row, actor)

    async def _drop(self, row: dict[str, Any], actor: str) -> None:
        task_ids = await self.repo.delete_automation(row["id"])
        await self.repo.audit(
            self.workspace_id, actor, "automation.deleted", {"automation_id": row["id"], "name": row["name"]}
        )
        await self._delete_tasks(task_ids)

    async def _delete_tasks(self, task_ids: list[str]) -> None:
        for task_id in task_ids:
            with contextlib.suppress(TaskError):
                await self.orchestrator.delete(task_id)

    def _toggle(self, schedule: Schedule, enabled: bool) -> dict[str, Any]:
        if enabled:
            return {"enabled": True, "failures": 0, "disabled_reason": None, "next_run_at": first_run(schedule)}
        return {"enabled": False, "next_run_at": None}

    async def _check_target(self, target_id: str) -> None:
        target = await self.repo.get_target(target_id)
        if not target or target["status"] == "revoked":
            raise AutomationError("unknown or revoked device")

    # ---- runs ---------------------------------------------------------------

    async def run(self, automation_id: str, trigger: RunTrigger = "manual") -> dict[str, Any]:
        async with self.lock:
            row = await self._row(automation_id)
            if row["running_run_id"]:
                raise AutomationError("automation is already running", 409)
            return await self._launch(row, trigger)

    async def _launch(self, row: dict[str, Any], trigger: RunTrigger) -> dict[str, Any]:
        run = {
            "id": new_id("run"),
            "automation_id": row["id"],
            "task_id": None,
            "trigger": trigger,
            "status": "running",
            "result": None,
            "error": None,
            "started_at": now_iso(),
            "finished_at": None,
            "duration_ms": None,
        }
        await self.repo.create_run(run)
        await self.repo.update_automation(row["id"], {"running_run_id": run["id"]})
        await self.repo.audit(
            self.workspace_id,
            "core",
            "automation.run.started",
            {"automation_id": row["id"], "run_id": run["id"], "trigger": trigger},
        )
        task = asyncio.create_task(self._execute(row, run["id"], trigger))
        self.running[row["id"]] = task
        task.add_done_callback(lambda t: self._forget(row["id"], t))
        return run

    def _forget(self, automation_id: str, task: asyncio.Task[None]) -> None:
        if self.running.get(automation_id) is task:
            del self.running[automation_id]

    async def _execute(self, row: dict[str, Any], run_id: str, trigger: RunTrigger) -> None:
        started = time.monotonic()
        status: RunStatus = "error"
        result: str | None = None
        error: str | None = None
        try:
            task = await self.orchestrator.create_task(
                PROFILE, row["target_id"], row["prompt"], row["mode"], row.get("model"), automation_id=row["id"]
            )
            await self.repo.update_run(run_id, {"task_id": task["id"]})
            final = await self._wait(row, task["id"])
            if final is None:
                with contextlib.suppress(TaskError):
                    await self.orchestrator.cancel(task["id"])
                status, error = "timeout", f"no result in {row['timeout_s']} s"
            elif final["status"] == "SUCCEEDED":
                text = (final.get("result") or "").strip()
                status, result = "ok", (text if text and text != NO_REPLY else None)
            elif final["status"] == "CANCELED":
                status, error = "canceled", final.get("status_reason")
            else:
                error = final.get("status_reason") or final["status"]
        except TaskError as e:
            error = str(e)
        except Exception as e:
            log.exception("automation run crashed", extra={"automation_id": row["id"]})
            error = f"internal error: {e}"
        await self._finish(row, run_id, trigger, status, result, error, int((time.monotonic() - started) * 1000))

    async def _wait(self, row: dict[str, Any], task_id: str) -> dict[str, Any] | None:
        deadline = time.monotonic() + row["timeout_s"]
        asked = False
        while True:
            expired = time.monotonic() >= deadline
            task = await self.repo.get_task(task_id)
            if task is None:
                raise TaskError("the task was deleted")
            if task["status"] in TERMINAL_STATUSES and task_id not in self.orchestrator.runners:
                return task
            if task["status"] == "WAITING_APPROVAL" and not asked:
                asked = True
                url = f"{self.public_url.rstrip('/')}/#/chat/{task_id}"
                await self._send(row, f"**{row['name']}** is waiting for your approval: {url}")
            if expired:
                return None
            await asyncio.sleep(POLL_S)

    async def _finish(
        self,
        row: dict[str, Any],
        run_id: str,
        trigger: RunTrigger,
        status: RunStatus,
        result: str | None,
        error: str | None,
        duration_ms: int,
    ) -> None:
        await self.repo.update_run(
            run_id,
            {"status": status, "result": result, "error": error, "finished_at": now_iso(), "duration_ms": duration_ms},
        )
        values: dict[str, Any] = {"running_run_id": None}
        try:
            await self.repo.audit(
                self.workspace_id,
                "core",
                "automation.run.finished",
                {"automation_id": row["id"], "run_id": run_id, "status": status},
            )
            current = await self.repo.get_automation(row["id"])
            if current is None:
                return
            failures = 0 if status == "ok" else current["failures"] + 1
            after = _after_run(current, Schedule.model_validate(current["schedule"]), status, failures, trigger)
            if after is None:
                await self._drop(current, "core")
            else:
                last = {"last_run_at": now_iso(), "last_status": status, "last_error": error, "failures": failures}
                values |= last | after
        finally:
            await self.repo.update_automation(row["id"], values)
        await self._notify(current, status, result, error)
        if after is not None:
            pruned = await self.repo.prune_runs(current["id"], KEEP_RUNS, iso(utcnow() - timedelta(days=KEEP_DAYS)))
            await self._delete_tasks([t for t in pruned if t not in self.orchestrator.runners])

    async def _notify(self, row: dict[str, Any], status: RunStatus, result: str | None, error: str | None) -> None:
        if status == "canceled" or (status == "ok" and not result):
            return
        if status == "ok":
            await self._send(row, f"**{row['name']}**\n\n{result}")
        else:
            await self._send(row, f"**{row['name']}**: run {status}" + (f"\n\n{error}" if error else ""))

    async def _send(self, row: dict[str, Any], text: str) -> None:
        tg = self.channels.telegram
        if not row["notify"] or tg is None or not tg.chat_id:
            return
        try:
            await tg.reply(text)
        except Exception as e:
            log.warning("automation notification failed", extra={"automation_id": row["id"], "error": str(e)})
