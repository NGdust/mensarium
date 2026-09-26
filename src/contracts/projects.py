import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from mensarium.shared.redaction import SECRET_FILE_PATTERNS

ProjectKind = Literal["repo", "folder"]
ProjectOpName = Literal["browse", "checkout", "commit", "status", "remove"]
OpState = Literal["ok", "conflict", "error"]
SnapshotState = Literal["ok", "unchanged", "error"]

SNAPSHOT_REF = "refs/mensarium/snapshot"
BRANCH_PREFIX = "mensarium/"
SECRET_EXCLUDES: tuple[str, ...] = (*SECRET_FILE_PATTERNS, ".netrc", ".npmrc", ".pypirc", "*.kdbx", "credentials*", "secrets.*")
FOLDER_EXCLUDES = (".DS_Store", "Thumbs.db", "~$*", "*.tmp", ".~lock.*")
KIND_LABELS = {"repo": "git repository", "folder": "folder"}


class ProjectError(Exception):
    pass


def branch_name(task_id: str, text: str) -> str:
    slug = "-".join(re.findall(r"[a-z0-9]+", text.lower()))[:40].rstrip("-") or "chat"
    return f"{BRANCH_PREFIX}{slug}-{task_id[-4:].lower()}"


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_target_id: str = Field(max_length=100)
    source_path: str = Field(min_length=1, max_length=1000)
    include_remotes: bool = True
    fetch_origin: bool = False

    @field_validator("source_path")
    @classmethod
    def _strip_slash(cls, value: str) -> str:
        path = value.strip()
        path = path.rstrip("/") or path[:1]
        if not path:
            raise ValueError("source_path is empty")
        return path


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    include_remotes: bool | None = None
    fetch_origin: bool | None = None
    default_base: str | None = Field(None, min_length=1, max_length=200)
    size_limit_mb: int | None = Field(None, ge=1, le=20480)
    file_limit_mb: int | None = Field(None, ge=1, le=2048)


class BrowseBody(BaseModel):
    target_id: str = Field(max_length=100)
    path: str = Field("~", max_length=1000)


class ProjectSnapshot(BaseModel):
    type: Literal["project.snapshot"] = "project.snapshot"
    request_id: str
    target_id: str
    project_id: str
    source_path: str
    kind: ProjectKind | None = None
    include_remotes: bool = True
    fetch_origin: bool = False
    size_limit_mb: int = 1024
    file_limit_mb: int = 100
    known: dict[str, str] = {}
    issued_at: str
    expires_at: str
    nonce: str
    signature: str = ""


class ProjectSnapshotStatus(BaseModel):
    type: Literal["project.snapshot.status"] = "project.snapshot.status"
    request_id: str
    project_id: str
    state: SnapshotState
    kind: ProjectKind | None = None
    head_sha: str | None = None
    snapshot_sha: str | None = None
    branch: str | None = None
    refs: dict[str, str] = {}
    size_bytes: int = 0
    skipped: list[str] = []
    detail: str = ""
    signature: str = ""


class ProjectOp(BaseModel):
    type: Literal["project.op"] = "project.op"
    request_id: str
    target_id: str
    project_id: str
    task_id: str
    op: ProjectOpName
    args: dict[str, Any] = {}
    issued_at: str
    expires_at: str
    nonce: str
    signature: str = ""


class ProjectOpStatus(BaseModel):
    type: Literal["project.op.status"] = "project.op.status"
    request_id: str
    project_id: str
    task_id: str
    op: ProjectOpName
    state: OpState
    head_sha: str | None = None
    changed: int = 0
    detail: str = ""
    conflicts: list[str] = []
    data: dict[str, Any] = {}
    signature: str = ""
