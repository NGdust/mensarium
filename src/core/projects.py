import asyncio
import contextlib
import logging
import secrets
from typing import Any

from pydantic import ValidationError

from mensarium.contracts.projects import (
    KIND_LABELS,
    ProjectCreate,
    ProjectError,
    ProjectKind,
    ProjectOp,
    ProjectOpName,
    ProjectOpStatus,
    ProjectPatch,
    ProjectSnapshot,
    ProjectSnapshotStatus,
)
from mensarium.core.client_hub import ClientHub, TargetUnavailable
from mensarium.core.repo import Repo
from mensarium.shared.ids import new_id
from mensarium.shared.timeutil import iso_in, now_iso

log = logging.getLogger(__name__)

OP_TIMEOUT_S = 600
BROWSE_TIMEOUT_S = 30
DIFF_TIMEOUT_S = 60


class ProjectManager:
    def __init__(self, repo: Repo, workspace_id: str, hub: ClientHub, ttl_s: int) -> None:
        self.repo = repo
        self.workspace_id = workspace_id
        self.hub = hub
        self.ttl_s = max(ttl_s, OP_TIMEOUT_S)
        self.jobs: dict[str, asyncio.Task[None]] = {}
        # The Core's own device: repositories given by URL are cloned there.
        self.device_id: str | None = None

    # ---- lifecycle --------------------------------------------------------------

    async def start(self) -> None:
        for p in await self.repo.list_projects():
            if p["status"] == "creating":
                await self.repo.update_project(str(p["id"]), {"status": "error", "error": "interrupted by Core restart"})

    async def stop(self) -> None:
        jobs = list(self.jobs.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        self.jobs.clear()

    # ---- views ------------------------------------------------------------------

    def view(self, p: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "id", "name", "kind", "source_target_id", "source_name", "source_path", "default_executor_id", "default_base",
            "git_url", "include_remotes", "fetch_origin", "size_limit_mb", "file_limit_mb", "head_sha", "snapshot_sha",
            "default_branch", "last_sync_at", "size_bytes", "status", "error", "created_at", "updated_at", "chats", "instructions",
        )
        return {k: p.get(k) for k in keys} | {
            "skipped": p.get("skipped") or [],
            "kind_label": KIND_LABELS.get(str(p.get("kind")), str(p.get("kind"))),
            "source_online": self.hub.is_online(str(p["source_target_id"])),
            "syncing": str(p["id"]) in self.jobs,
        }

    async def all(self) -> list[dict[str, Any]]:
        return [self.view(p) for p in await self.repo.list_projects()]

    async def get(self, project_id: str) -> dict[str, Any]:
        p = await self.repo.get_project(project_id)
        if not p:
            raise ProjectError("project not found")
        return p

    # ---- device calls -----------------------------------------------------------

    def can(self, target_id: str, op: str) -> bool:
        hello = self.hub.hello(target_id)
        return bool(hello and op in hello.capabilities.project_ops)

    def _supports(self, target: dict[str, Any] | None) -> dict[str, Any]:
        if not target or target["status"] == "revoked":
            raise ProjectError("unknown or revoked device")
        hello = self.hub.hello(str(target["id"]))
        if hello is None:
            raise ProjectError("the device is offline")
        if not hello.capabilities.projects or not hello.capabilities.projects_root:
            raise ProjectError("this device's client does not support projects; update it and make sure git is installed")
        return target

    async def _op(
        self, target_id: str, project_id: str, task_id: str, op: ProjectOpName, args: dict[str, Any], timeout_s: float | None = None
    ) -> ProjectOpStatus:
        msg = ProjectOp(
            request_id=new_id("pop"),
            target_id=target_id,
            project_id=project_id,
            task_id=task_id,
            op=op,
            args=args,
            issued_at=now_iso(),
            expires_at=iso_in(self.ttl_s),
            nonce=secrets.token_hex(32),
        )
        raw = await self.hub.project_request(msg, timeout_s or self.ttl_s)
        return ProjectOpStatus.model_validate(raw)

    async def _snapshot(self, p: dict[str, Any], kind: ProjectKind | None) -> ProjectSnapshotStatus:
        msg = ProjectSnapshot(
            request_id=new_id("psn"),
            target_id=str(p["source_target_id"]),
            project_id=str(p["id"]),
            source_path=str(p["source_path"]),
            kind=kind,
            git_url=p.get("git_url"),
            include_remotes=bool(p.get("include_remotes", True)),
            fetch_origin=bool(p.get("fetch_origin", False)),
            size_limit_mb=int(p.get("size_limit_mb") or 1024),
            file_limit_mb=int(p.get("file_limit_mb") or 100),
            issued_at=now_iso(),
            expires_at=iso_in(self.ttl_s),
            nonce=secrets.token_hex(32),
        )
        raw = await self.hub.project_request(msg, self.ttl_s)
        return ProjectSnapshotStatus.model_validate(raw)

    def _snapshot_args(self, p: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_path": p["source_path"],
            "kind": p["kind"],
            "git_url": p.get("git_url"),
            "include_remotes": bool(p.get("include_remotes", True)),
            "fetch_origin": bool(p.get("fetch_origin", False)),
            "size_limit_mb": int(p.get("size_limit_mb") or 1024),
            "file_limit_mb": int(p.get("file_limit_mb") or 100),
        }

    async def _cleanup(self, target_id: str, project_id: str, task_id: str, args: dict[str, Any]) -> None:
        try:
            status = await self._op(target_id, project_id, task_id, "remove", args)
        except (TargetUnavailable, ValidationError) as e:
            log.warning("project cleanup failed", extra={"project_id": project_id, "task_id": task_id, "error": str(e)})
            return
        if status.state != "ok":
            log.warning("project cleanup failed", extra={"project_id": project_id, "task_id": task_id, "error": status.detail})

    # ---- public -----------------------------------------------------------------

    async def browse(self, target_id: str, path: str) -> dict[str, Any]:
        self._supports(await self.repo.get_target(target_id))
        try:
            status = await self._op(target_id, "", "", "browse", {"path": path}, BROWSE_TIMEOUT_S)
        except TargetUnavailable as e:
            raise ProjectError(str(e)) from e
        if status.state != "ok":
            raise ProjectError(status.detail or "cannot list this folder")
        return status.data

    async def branches(self, project_id: str) -> dict[str, Any]:
        p = await self.get(project_id)
        target = self._supports(await self.repo.get_target(str(p["source_target_id"])))
        if p["kind"] != "repo":
            return {"branches": [], "default": None, "current": None}
        if not self.can(str(target["id"]), "branches"):
            raise ProjectError("this device's client is outdated; update it to pick a branch")
        try:
            status = await self._op(str(target["id"]), project_id, "", "branches", self._snapshot_args(p), BROWSE_TIMEOUT_S)
        except TargetUnavailable as e:
            raise ProjectError(str(e)) from e
        if status.state != "ok":
            raise ProjectError(status.detail or "cannot list the branches")
        # "default" is where a new chat starts: the project's own choice, else the repository's main branch.
        base = p.get("default_base")
        main = status.data.get("default")
        return {**status.data, "main": main, "default": base if base not in (None, "snapshot", "default") else main}

    async def changes(self, task: dict[str, Any], path: str | None = None) -> dict[str, Any]:
        if not task.get("project_id") or task.get("parent_id"):
            raise ProjectError("this chat is not in a project")
        if not task.get("base_sha"):
            return {"ready": False, "files": []}
        target_id = str(task["target_id"])
        self._supports(await self.repo.get_target(target_id))
        if not self.can(target_id, "diff"):
            raise ProjectError("this device's client is outdated; update it to see the changes")
        args = {"base_sha": task["base_sha"], **({"path": path} if path else {})}
        try:
            status = await self._op(target_id, str(task["project_id"]), str(task["id"]), "diff", args, DIFF_TIMEOUT_S)
        except TargetUnavailable as e:
            raise ProjectError(str(e)) from e
        if status.state != "ok":
            raise ProjectError(status.detail or "cannot read the changes")
        return {"ready": True, **status.data}

    async def revert(self, task: dict[str, Any], path: str) -> None:
        if not task.get("project_id") or task.get("parent_id") or not task.get("base_sha"):
            raise ProjectError("this chat has no working copy")
        target_id = str(task["target_id"])
        self._supports(await self.repo.get_target(target_id))
        if not self.can(target_id, "revert"):
            raise ProjectError("this device's client is outdated; update it to revert files")
        try:
            status = await self._op(target_id, str(task["project_id"]), str(task["id"]), "revert", {"base_sha": task["base_sha"], "path": path}, DIFF_TIMEOUT_S)
        except TargetUnavailable as e:
            raise ProjectError(str(e)) from e
        if status.state != "ok":
            raise ProjectError(status.detail or "cannot revert the file")

    async def docs(self, project_id: str) -> dict[str, Any]:
        p = await self.get(project_id)
        target = self._supports(await self.repo.get_target(str(p["source_target_id"])))
        if not self.can(str(target["id"]), "docs"):
            raise ProjectError("this device's client is outdated; update it to see the project's files")
        try:
            status = await self._op(str(target["id"]), project_id, "", "docs", self._snapshot_args(p), BROWSE_TIMEOUT_S)
        except TargetUnavailable as e:
            raise ProjectError(str(e)) from e
        if status.state != "ok":
            raise ProjectError(status.detail or "cannot read the project's files")
        return status.data

    async def create(self, body: ProjectCreate) -> dict[str, Any]:
        project_id = new_id("prj")
        if body.git_url:
            if not self.device_id:
                raise ProjectError("the Core has no device of its own; enable it in the Core config")
            target = self._supports(await self.repo.get_target(self.device_id))
            hello = self.hub.hello(str(target["id"]))
            source_path = f"{hello.capabilities.projects_root if hello else ''}/{project_id}/src"
        else:
            target = self._supports(await self.repo.get_target(str(body.source_target_id)))
            source_path = str(body.source_path)
            if await self.repo.find_project(str(target["id"]), source_path):
                raise ProjectError("this folder is already a project")
        now = now_iso()
        await self.repo.create_project(
            {
                "id": project_id,
                "workspace_id": self.workspace_id,
                "name": body.name.strip(),
                "kind": "repo" if body.git_url else "folder",
                "source_target_id": target["id"],
                "source_path": source_path,
                "git_url": body.git_url,
                "include_remotes": int(body.include_remotes),
                "fetch_origin": int(body.fetch_origin or bool(body.git_url)),
                "status": "creating",
                "created_at": now,
                "updated_at": now,
            }
        )
        await self.repo.audit(
            self.workspace_id, "user", "project.created", {"project_id": project_id, "target_id": target["id"], "path": source_path, "git_url": body.git_url}
        )
        self._start_refresh(project_id, detect=not body.git_url)
        return self.view(await self.get(project_id))

    async def sync(self, project_id: str) -> dict[str, Any]:
        p = await self.get(project_id)
        self._supports(await self.repo.get_target(str(p["source_target_id"])))
        if project_id in self.jobs:
            raise ProjectError("the project is already being read")
        self._start_refresh(project_id, detect=p["snapshot_sha"] is None)
        return self.view(p)

    def _start_refresh(self, project_id: str, detect: bool) -> None:
        job = asyncio.create_task(self._refresh_job(project_id, detect))
        self.jobs[project_id] = job
        job.add_done_callback(lambda t: self._forget(project_id, t))

    def _forget(self, project_id: str, job: asyncio.Task[None]) -> None:
        if self.jobs.get(project_id) is job:
            del self.jobs[project_id]

    async def _refresh_job(self, project_id: str, detect: bool) -> None:
        try:
            await self._refresh(await self.get(project_id), detect)
        except Exception as e:
            if not isinstance(e, ProjectError | TargetUnavailable):
                log.exception("project snapshot failed", extra={"project_id": project_id})
            error = (str(e).strip() or type(e).__name__).splitlines()[0][:300]
            with contextlib.suppress(Exception):
                await self.repo.update_project(project_id, {"status": "error", "error": error})

    async def _refresh(self, p: dict[str, Any], detect: bool) -> None:
        self._supports(await self.repo.get_target(str(p["source_target_id"])))
        status = await self._snapshot(p, None if detect else p["kind"])
        if status.state == "error":
            raise ProjectError(status.detail or "the device could not snapshot the folder")
        await self.repo.update_project(
            str(p["id"]),
            {
                "kind": status.kind or p["kind"],
                "head_sha": status.head_sha,
                "snapshot_sha": status.snapshot_sha,
                "default_branch": status.branch,
                "size_bytes": status.size_bytes,
                "skipped": status.skipped,
                "last_sync_at": now_iso(),
                "status": "ready",
                "error": None,
            },
        )
        await self.repo.audit(self.workspace_id, "core", "project.synced", {"project_id": p["id"], "snapshot_sha": status.snapshot_sha, "size_bytes": status.size_bytes})

    async def update(self, project_id: str, body: ProjectPatch) -> dict[str, Any]:
        await self.get(project_id)
        values = {k: (int(v) if isinstance(v, bool) else v) for k, v in body.model_dump(exclude_none=True).items()}
        if body.instructions is not None:
            values["instructions"] = body.instructions.strip() or None
        if values:
            await self.repo.update_project(project_id, values)
        return self.view(await self.get(project_id))

    async def precheck_delete(self, project_id: str, remove_shadow: bool) -> dict[str, Any]:
        p = await self.get(project_id)
        if project_id in self.jobs:
            raise ProjectError("the project is being read; try again in a moment")
        if remove_shadow and p["kind"] == "folder" and not self.hub.is_online(str(p["source_target_id"])):
            raise ProjectError("the source device is offline; delete without removing its hidden history or turn the device on")
        return p

    async def delete_row(self, project_id: str, remove_shadow: bool) -> None:
        p = await self.precheck_delete(project_id, remove_shadow)
        if remove_shadow or p["kind"] == "repo":
            await self._cleanup(str(p["source_target_id"]), project_id, "", {**self._snapshot_args(p), "delete_shadow": remove_shadow, "delete_clone": bool(p.get("git_url"))})
        await self.repo.delete_project(project_id)
        await self.repo.audit(self.workspace_id, "user", "project.deleted", {"project_id": project_id})

    # ---- per-task ---------------------------------------------------------------

    def worktree(self, project: dict[str, Any], target: dict[str, Any], task_id: str) -> str:
        hello = self.hub.hello(str(target["id"]))
        root = (hello.capabilities.projects_root if hello else None) or (target.get("capabilities") or {}).get("projects_root")
        if not root:
            raise ProjectError("this device's client does not support projects")
        return f"{root}/{project['id']}/wt/{task_id}"

    async def checkout(self, project: dict[str, Any], task: dict[str, Any]) -> ProjectOpStatus:
        self._supports(await self.repo.get_target(str(task["target_id"])))
        # An older client knows only the snapshot start; a repo chat on a newer one starts from a branch.
        start = "snapshot"
        if project["kind"] == "repo" and self.can(str(task["target_id"]), "branches"):
            start = str(task.get("base_ref") or "default")
        args = {**self._snapshot_args(project), "branch": task["branch"], "start": start}
        status = await self._op(str(task["target_id"]), str(project["id"]), str(task["id"]), "checkout", args, timeout_s=OP_TIMEOUT_S)
        if status.state == "ok":
            status.data.setdefault("base", start)
        return status

    async def commit(self, project: dict[str, Any], task: dict[str, Any], message: str) -> ProjectOpStatus:
        args = {**self._snapshot_args(project), "message": message, "base_sha": task.get("base_sha")}
        return await self._op(str(task["target_id"]), str(project["id"]), str(task["id"]), "commit", args)

    async def remove(self, project: dict[str, Any], task: dict[str, Any]) -> None:
        args = {**self._snapshot_args(project), "branch": task.get("branch"), "delete_branch": project["kind"] == "folder"}
        await self._cleanup(str(task["target_id"]), str(project["id"]), str(task["id"]), args)
