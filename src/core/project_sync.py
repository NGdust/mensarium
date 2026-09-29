"""Keeps the Core's mirror of a project in step with its devices: snapshots come up, chat branches go in."""

import asyncio
import logging
import re
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, Any

from mensarium.contracts.projects import (
    DEVICE_REFS,
    ProjectError,
    ProjectOpStatus,
    ProjectSnapshotStatus,
    device_ref,
    mirror_ref,
)
from mensarium.core.client_hub import ClientHub
from mensarium.core.mirror import Mirror, MirrorError
from mensarium.core.repo import Repo
from mensarium.shared import bundles
from mensarium.shared.paths import projects_dir
from mensarium.shared.timeutil import now_iso, parse_iso, utcnow

if TYPE_CHECKING:
    from mensarium.core.projects import ProjectManager

log = logging.getLogger(__name__)
TICK_S = 60
SHA_RE = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")


class ProjectSync:
    def __init__(self, repo: Repo, workspace_id: str, hub: ClientHub, manager: "ProjectManager", interval_s: int) -> None:
        self.repo = repo
        self.workspace_id = workspace_id
        self.hub = hub
        self.manager = manager
        self.interval_s = interval_s
        self.inbox = projects_dir() / "inbox"
        shutil.rmtree(self.inbox, ignore_errors=True)
        hub.inbox = self.inbox

    def mirror(self, project_id: str) -> Mirror:
        return Mirror(project_id)

    def inbox_file(self, request_id: str) -> Path:
        return self.inbox / f"{request_id}.bundle"

    def can_bundle(self, target_id: str) -> bool:
        hello = self.hub.hello(target_id)
        return bool(hello and "bundle" in hello.capabilities.project_ops)

    # ---- source -> mirror ---------------------------------------------------------

    async def sync_source(self, p: dict[str, Any]) -> ProjectSnapshotStatus:
        project_id, src = str(p["id"]), str(p["source_target_id"])
        mirror = self.mirror(project_id)
        bundling = Mirror.enabled() and self.can_bundle(src)
        known: dict[str, str] = {}
        if bundling:
            try:
                await mirror.init()
                have = await mirror.refs()
            except MirrorError as e:
                raise ProjectError(f"cannot open the project mirror: {e}") from e
            device = await self.repo.get_project_device(project_id, src)
            # Trust the mirror over the row: a ref the mirror lost must be sent again.
            known = {ref: sha for ref, sha in ((device or {}).get("device_refs") or {}).items() if have.get(mirror_ref(src, ref) or "") == sha}
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
            refspecs = {ref: mref for ref in status.bundle.refs if (mref := mirror_ref(src, ref))}
            if refspecs:
                await mirror.fetch_bundle(path, refspecs)
        have = await mirror.refs()
        for ref, sha in status.refs.items():
            # A ref moved to a commit the mirror already has (a branch reset back) comes without a bundle.
            mref = mirror_ref(src, ref)
            if mref and have.get(mref) != sha and SHA_RE.fullmatch(sha) and await mirror.rev(sha):
                await mirror.update_ref(mref, sha)
        for mref in have:
            if mref.startswith(f"{DEVICE_REFS}{src}/") and (dref := device_ref(src, mref)) and dref not in status.refs:
                await mirror.delete_ref(mref)

    async def on_connect(self, target_id: str) -> None:
        if not self.can_bundle(target_id):
            return
        for p in await self.repo.list_projects():
            if p["source_target_id"] == target_id and p["status"] != "creating":
                await self.manager.refresh(str(p["id"]))

    async def run_forever(self) -> None:
        while True:
            await asyncio.sleep(TICK_S)
            try:
                await self._tick()
            except Exception:
                log.exception("project sync tick failed")

    async def _tick(self) -> None:
        for p in await self.repo.list_projects():
            last = p.get("last_sync_at")
            due = last is None or (utcnow() - parse_iso(str(last))).total_seconds() >= self.interval_s
            if due and p["status"] == "ready" and self.can_bundle(str(p["source_target_id"])):
                await self.manager.refresh(str(p["id"]))

    # ---- executor -> mirror --------------------------------------------------------

    async def publish(self, project: dict[str, Any], task: dict[str, Any], status: ProjectOpStatus) -> None:
        path = self.inbox_file(status.request_id)
        try:
            if status.bundle is None or not task.get("branch") or not Mirror.enabled():
                return
            mirror = self.mirror(str(project["id"]))
            ref = f"refs/heads/{task['branch']}"
            bundles.check(path, status.bundle)
            await mirror.init()
            await mirror.fetch_bundle(path, {ref: ref})
            role = "source" if task["target_id"] == project["source_target_id"] else "executor"
            await self.repo.upsert_project_device(str(project["id"]), str(task["target_id"]), role)
        except (ValueError, MirrorError) as e:
            raise ProjectError(f"cannot store the chat branch: {e}") from e
        finally:
            path.unlink(missing_ok=True)
