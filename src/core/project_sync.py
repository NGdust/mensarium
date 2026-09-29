"""Keeps the Core's mirror of a project in step with its devices: snapshots come up, chat branches go in."""

import asyncio
import logging
import re
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from mensarium.contracts.projects import (
    CHAT_REFS,
    DEVICE_REFS,
    ProjectError,
    ProjectOpStatus,
    ProjectSnapshotStatus,
    device_ref,
    mirror_ref,
)
from mensarium.core.client_hub import ClientHub, TargetUnavailable
from mensarium.core.mirror import Mirror, MirrorError
from mensarium.core.repo import Repo
from mensarium.shared import bundles
from mensarium.shared.ids import new_id
from mensarium.shared.paths import ensure_private_dir, projects_dir
from mensarium.shared.timeutil import now_iso, parse_iso, utcnow

if TYPE_CHECKING:
    from mensarium.core.projects import ProjectManager

log = logging.getLogger(__name__)
TICK_S = 60
SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
DIVERGED = "the branch on the device has commits the chat does not have"
OUTDATED = "update the Mensarium client on this device to receive branches"


class ProjectSync:
    def __init__(self, repo: Repo, workspace_id: str, hub: ClientHub, manager: "ProjectManager", interval_s: int) -> None:
        self.repo = repo
        self.workspace_id = workspace_id
        self.hub = hub
        self.manager = manager
        self.interval_s = interval_s
        # Not "inbox": the Core's own device runs a client in this process over the same projects folder.
        self.inbox = projects_dir() / "core-inbox"
        shutil.rmtree(self.inbox, ignore_errors=True)
        hub.inbox = self.inbox
        self.locks: dict[str, asyncio.Lock] = {}
        self.jobs: set[asyncio.Task[None]] = set()
        # When each project was last read, failed reads included: the timer waits a full interval after either.
        self.attempts: dict[str, float] = {}

    def mirror(self, project_id: str) -> Mirror:
        return Mirror(project_id)

    def inbox_file(self, request_id: str) -> Path:
        return self.inbox / f"{request_id}.bundle"

    def can_bundle(self, target_id: str) -> bool:
        hello = self.hub.hello(target_id)
        return bool(hello and "bundle" in hello.capabilities.project_ops)

    def can_fetch(self, target_id: str) -> bool:
        hello = self.hub.hello(target_id)
        return bool(hello and {"bundle", "fetch"} <= set(hello.capabilities.project_ops))

    # ---- source -> mirror ---------------------------------------------------------

    async def sync_source(self, p: dict[str, Any]) -> ProjectSnapshotStatus:
        project_id, src = str(p["id"]), str(p["source_target_id"])
        self.attempts[project_id] = time.monotonic()
        mirror = self.mirror(project_id)
        bundling = Mirror.enabled() and self.can_bundle(src)
        known: dict[str, str] = {}
        if bundling:
            try:
                await mirror.init()
                have = await mirror.refs(f"{DEVICE_REFS}{src}/")
            except MirrorError as e:
                raise ProjectError(f"cannot open the project mirror: {e}") from e
            device = await self.repo.get_project_device(project_id, src)
            # Trust the mirror over the row for the device's own refs: one the mirror lost must be sent again.
            # Chat branches reach the mirror only through publish, so the device's values stand for them,
            # as long as the mirror has that commit (the device cuts its bundle there).
            for ref, sha in ((device or {}).get("device_refs") or {}).items():
                if have.get(mirror_ref(src, ref) or "") == sha or (ref.startswith(CHAT_REFS) and SHA_RE.fullmatch(sha) and await mirror.rev(sha)):
                    known[ref] = sha
            # A chat branch the Core delivered, not reported yet or moved on by the user: an older client cuts it there.
            for ref, sha in ((device or {}).get("known_refs") or {}).items():
                if ref.startswith(CHAT_REFS) and ref not in known and SHA_RE.fullmatch(sha) and await mirror.rev(sha):
                    known[ref] = sha
        msg = self.manager.snapshot_request(p, known, bundling)
        path = self.inbox_file(msg.request_id)
        try:
            status = ProjectSnapshotStatus.model_validate(await self.hub.project_request(msg, self.manager.ttl_s))
            if status.state == "error":
                raise ProjectError(status.detail or "the device could not snapshot the folder")
            if bundling:
                try:
                    await self._store(mirror, src, status, path)
                except (ValueError, MirrorError) as e:
                    raise ProjectError(f"cannot store the snapshot: {e}") from e
                await self.repo.upsert_project_device(project_id, src, "source", device_refs=status.refs, last_sync_at=now_iso(), last_error=None)
        finally:
            path.unlink(missing_ok=True)
        return status

    async def _store(self, mirror: Mirror, src: str, status: ProjectSnapshotStatus, path: Path) -> None:
        if status.bundle is not None:
            bundles.check(path, status.bundle)
            refspecs = {ref: mref for ref in status.bundle.refs if not ref.startswith(CHAT_REFS) and (mref := mirror_ref(src, ref))}
            if refspecs:
                await mirror.fetch_bundle(path, refspecs)
        have = await mirror.refs(f"{DEVICE_REFS}{src}/")
        for ref, sha in status.refs.items():
            # A ref moved to a commit the mirror already has (a branch reset back) comes without a bundle.
            mref = None if ref.startswith(CHAT_REFS) else mirror_ref(src, ref)
            if mref and have.get(mref) != sha and SHA_RE.fullmatch(sha) and await mirror.rev(sha):
                await mirror.update_ref(mref, sha)
        for mref in have:
            if (dref := device_ref(src, mref)) and dref not in status.refs:
                await mirror.delete_ref(mref)

    async def on_connect(self, target_id: str) -> None:
        if not self.can_bundle(target_id):
            return
        for p in await self.repo.list_projects():
            if self.manager.stopped:
                return
            if p["source_target_id"] == target_id and p["status"] != "creating":
                await self.manager.refresh(str(p["id"]))
        await self.deliver(target_id)

    async def run_forever(self) -> None:
        while not self.manager.stopped:
            await asyncio.sleep(TICK_S)
            try:
                await self._tick()
            except Exception:
                log.exception("project sync tick failed")

    async def _tick(self) -> None:
        for p in await self.repo.list_projects():
            last, tried = p.get("last_sync_at"), self.attempts.get(str(p["id"]))
            due = last is None or (utcnow() - parse_iso(str(last))).total_seconds() >= self.interval_s
            due = due and (tried is None or time.monotonic() - tried >= self.interval_s)
            if due and p["status"] == "ready" and self.can_bundle(str(p["source_target_id"])):
                await self.manager.refresh(str(p["id"]))

    # ---- executor -> mirror --------------------------------------------------------

    async def publish(self, project: dict[str, Any], task: dict[str, Any], status: ProjectOpStatus) -> None:
        path = self.inbox_file(status.request_id)
        role = "source" if task["target_id"] == project["source_target_id"] else "executor"
        try:
            if status.bundle is None or not task.get("branch") or not Mirror.enabled() or project["id"] in self.manager.deleting:
                return
            mirror = self.mirror(str(project["id"]))
            ref = f"refs/heads/{task['branch']}"
            bundles.check(path, status.bundle)
            await mirror.init()
            await mirror.fetch_bundle(path, {ref: ref})
            await self.repo.upsert_project_device(str(project["id"]), str(task["target_id"]), role)
        except (ValueError, MirrorError) as e:
            raise ProjectError(f"cannot store the chat branch: {e}") from e
        finally:
            path.unlink(missing_ok=True)
        # A bundle came in, so the head moved: the source gets the chat branch back.
        if role == "executor":
            await self.queue(str(project["id"]), str(project["source_target_id"]), str(task["id"]), "branch")

    # ---- mirror -> executor and source -----------------------------------------------

    async def resolve_base(self, p: dict[str, Any], base_ref: str | None) -> tuple[str, str, str]:
        src, mirror = str(p["source_target_id"]), self.mirror(str(p["id"]))
        name, snapshot = base_ref or "snapshot", f"{DEVICE_REFS}{src}/snapshot"
        sha = await mirror.rev(snapshot) if mirror.exists else None
        if sha is None:
            raise ProjectError("the project has no snapshot on the Core yet; turn its device on and sync the project")
        if name == "snapshot":
            return name, snapshot, sha
        name = str(p.get("main_branch") or p.get("default_branch") or "main") if name == "default" else name
        for ref in (f"{DEVICE_REFS}{src}/heads/{name}", f"{DEVICE_REFS}{src}/remotes/{name}"):
            if sha := await mirror.rev(ref):
                return name, ref, sha
        raise ProjectError(f"branch {name} is not in the Core's copy of the project")

    async def ensure_objects(self, p: dict[str, Any], target_id: str, refs: dict[str, str]) -> None:
        project_id = str(p["id"])
        device = await self.repo.get_project_device(project_id, target_id)
        known = dict((device or {}).get("known_refs") or {})
        missing = {ref: sha for ref, sha in refs.items() if known.get(ref) != sha}
        if not missing:
            return
        role = "source" if target_id == p["source_target_id"] else "executor"
        if role == "executor":
            # The executor's copy is the Core's own: every ref it took is still there.
            have = list(known.values())
        else:
            # The user may drop a branch, so a source bundle falls back to one without prerequisites.
            have = list({*((device or {}).get("device_refs") or {}).values(), *known.values()})
        detail = None
        mirror = self.mirror(project_id)
        for prerequisites in ([have, []] if have else [[]]):
            request_id = new_id("pop")
            path = self.inbox_file(request_id)
            # The bundle carries the resolved commits under temporary names: a ref may move while the request is on its way.
            temp = {f"refs/mensarium/tmp/{request_id}/{n}": (ref, sha) for n, (ref, sha) in enumerate(missing.items())}
            try:
                ensure_private_dir(self.inbox)
                for name, (_, sha) in temp.items():
                    await mirror.update_ref(name, sha)
                info = await mirror.bundle(path, {name: sha for name, (_, sha) in temp.items()}, prerequisites)
                if info is None:
                    # The executor needs only the commits; the source needs the ref too, even to a commit it has.
                    if role == "executor" or not prerequisites:
                        return
                    continue
                args: dict[str, Any] = {"role": role, "kind": p["kind"], "bundle": info.model_dump(), "refs": {name: ref for name, (ref, _) in temp.items()}}
                if role == "source":
                    args |= self.manager.snapshot_args(p)
                status = await self.manager.op(target_id, project_id, "", "fetch", args, request_id=request_id, bundle=path)
                if status.state == "ok":
                    await self.repo.upsert_project_device(project_id, target_id, role, known_refs={**known, **missing})
                    return
                detail = status.detail
                if role == "source" and ("non-fast-forward" in (detail or "") or "rejected" in (detail or "")):
                    raise ProjectError(DIVERGED)
            except MirrorError as e:
                raise ProjectError(str(e)) from e
            finally:
                path.unlink(missing_ok=True)
                for name in temp:
                    await mirror.delete_ref(name)
        raise ProjectError(detail or "the device could not take the bundle")

    async def queue(self, project_id: str, target_id: str, task_id: str, kind: str, branch: str | None = None) -> None:
        # Checked under the device's lock: a running delivery either still sees the new head or has already finished.
        async with self.locks.setdefault(target_id, asyncio.Lock()):
            if not await self.repo.find_delivery(task_id, target_id, kind, ("pending", "failed")):
                now = now_iso()
                await self.repo.create_delivery(
                    {"id": new_id("dlv"), "project_id": project_id, "target_id": target_id, "task_id": task_id, "kind": kind, "branch": branch,
                     "status": "pending", "created_at": now, "updated_at": now}
                )
        if self.hub.is_online(target_id):
            # In the background: the chat's turn must not wait for a bundle to reach another device.
            job = asyncio.create_task(self._deliver_job(target_id))
            self.jobs.add(job)
            job.add_done_callback(self.jobs.discard)

    async def _deliver_job(self, target_id: str) -> None:
        try:
            await self.deliver(target_id)
        except Exception:
            log.exception("project delivery failed", extra={"target_id": target_id})

    async def deliver(self, target_id: str) -> None:
        if self.hub.hello(target_id) is None:
            return
        outdated = not self.can_fetch(target_id)
        async with self.locks.setdefault(target_id, asyncio.Lock()):
            for d in await self.repo.list_deliveries(target_id=target_id):
                if self.manager.stopped:
                    return
                p = await self.repo.get_project(str(d["project_id"]))
                task = await self.repo.get_task(str(d["task_id"]))
                if p is None or p["id"] in self.manager.deleting or (task is None and d["kind"] == "branch"):
                    await self.repo.update_delivery(str(d["id"]), {"status": "canceled"})
                    continue
                try:
                    if outdated and d["kind"] == "branch":
                        raise ProjectError(OUTDATED)
                    if d["kind"] == "branch":
                        assert task is not None
                        ref = f"refs/heads/{task['branch']}"
                        mirror = self.mirror(str(p["id"]))
                        sha = await mirror.rev(ref) if mirror.exists else None
                        if sha is None:
                            raise ProjectError("the chat branch is not in the Core's copy of the project")
                        await self.ensure_objects(p, target_id, {ref: sha})
                    else:
                        args = {"role": "executor", "branch": d.get("branch") or (task or {}).get("branch"), "delete_branch": True}
                        status = await self.manager.op(target_id, str(p["id"]), str(d["task_id"]), "remove", args)
                        if status.state != "ok":
                            raise ProjectError(status.detail or "the device could not remove the worktree")
                    await self.repo.update_delivery(str(d["id"]), {"status": "delivered", "error": None})
                    await self.repo.audit(self.workspace_id, "core", "project.delivered", {"delivery_id": d["id"], "task_id": d["task_id"], "target_id": target_id, "kind": d["kind"]})
                    if task:
                        await self.manager.bus_emit(str(task["id"]), {"kind": "delivered", "target_id": target_id})
                except (ProjectError, TargetUnavailable, ValidationError) as e:
                    await self.repo.update_delivery(str(d["id"]), {"status": "failed", "error": (str(e).strip() or type(e).__name__)[:300]})
                    if isinstance(e, TargetUnavailable):
                        return
