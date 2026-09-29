import re
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from mensarium.shared.redaction import SECRET_FILE_PATTERNS

ProjectKind = Literal["repo", "folder"]
ProjectOpName = Literal["browse", "checkout", "commit", "status", "remove", "branches", "diff", "docs", "revert", "fetch"]
# Ops a client lists in capabilities.project_ops; a client without them rejects the frame and never answers.
EXTRA_OPS: tuple[ProjectOpName, ...] = ("branches", "diff", "docs", "revert", "fetch")
# Also listed in capabilities.project_ops: "inplace" means the client takes a workdir anywhere in its allowed roots,
# so a repo chat without a workspace can work right in the project folder; "bundle" means it ships git bundles
# with its snapshot and commit answers and takes them back with the fetch op (phase 2 mirror on the Core).
PROJECT_FEATURES: tuple[str, ...] = (*EXTRA_OPS, "inplace", "bundle")
ProjectRole = Literal["source", "executor"]
OpState = Literal["ok", "conflict", "error"]
SnapshotState = Literal["ok", "unchanged", "error"]

SNAPSHOT_REF = "refs/mensarium/snapshot"
BRANCH_PREFIX = "mensarium/"
DEVICE_REFS = "refs/devices/"
CHAT_REFS = "refs/heads/" + BRANCH_PREFIX
SECRET_EXCLUDES: tuple[str, ...] = (*SECRET_FILE_PATTERNS, ".netrc", ".npmrc", ".pypirc", "*.kdbx", "credentials*", "secrets.*")
FOLDER_EXCLUDES = (".DS_Store", "Thumbs.db", "~$*", "*.tmp", ".~lock.*")
KIND_LABELS = {"repo": "git repository", "folder": "folder"}
# Instruction files other agents keep at a project root; shown in the project info, never put into prompts.
DOC_FILES = ("AGENTS.md", "CLAUDE.md")
INSTRUCTIONS_LIMIT = 20_000
# Only network transports: local paths, file:// and ext:: would let a clone reach into the device.
# A conservative subset of git-check-ref-format; the device checks the name with git itself as well.
BRANCH_RE = re.compile(r"(?![-/.])(?!.*\.\.)(?!.*//)(?!.*/\.)(?!.*@\{)(?!.*\.lock(/|$))[A-Za-z0-9._/+-]+(?<![./])")
GIT_URL_RE = re.compile(r"^(https?://|ssh://|git://)[^\s]+$|^[\w.-]+@[\w.-]+:[^\s]+$")


class ProjectError(Exception):
    pass


def branch_name(task_id: str, text: str) -> str:
    slug = "-".join(re.findall(r"[a-z0-9]+", text.lower()))[:40].rstrip("-") or "chat"
    return f"{BRANCH_PREFIX}{slug}-{task_id[-4:].lower()}"


def mirror_ref(target_id: str, ref: str) -> str | None:
    """A device's ref name as the mirror stores it; chat branches keep their name, anything else is not mirrored."""
    if ref.startswith(CHAT_REFS):
        return ref
    if ref == SNAPSHOT_REF:
        return f"{DEVICE_REFS}{target_id}/snapshot"
    for prefix in ("refs/heads/", "refs/remotes/"):
        if ref.startswith(prefix):
            return f"{DEVICE_REFS}{target_id}/{ref.removeprefix('refs/')}"
    return None


def device_ref(target_id: str, ref: str) -> str | None:
    if ref.startswith(CHAT_REFS):
        return ref
    own = f"{DEVICE_REFS}{target_id}/"
    if not ref.startswith(own):
        return None
    rest = ref.removeprefix(own)
    return SNAPSHOT_REF if rest == "snapshot" else f"refs/{rest}" if rest.startswith(("heads/", "remotes/")) else None


class BundleInfo(BaseModel):
    sha256: str
    size: int = Field(ge=0)
    refs: dict[str, str] = {}
    prerequisites: list[str] = []


class ProjectBundle(BaseModel):
    """One chunk of a git bundle on its way up or down; unsigned, tied to a pending signed request by request_id."""

    type: Literal["project.bundle"] = "project.bundle"
    request_id: str
    project_id: str
    seq: int = Field(ge=0)
    data: str


class ProjectCreate(BaseModel):
    """A folder on a device (`source_target_id` + `source_path`) or a repository to clone on the Core host (`git_url`)."""

    name: str = Field(min_length=1, max_length=120)
    source_target_id: str | None = Field(None, max_length=100)
    source_path: str | None = Field(None, min_length=1, max_length=1000)
    git_url: str | None = Field(None, min_length=1, max_length=1000)
    include_remotes: bool = True
    fetch_origin: bool = False

    @field_validator("source_path")
    @classmethod
    def _strip_slash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        path = value.strip()
        path = path.rstrip("/") or path[:1]
        if not path:
            raise ValueError("source_path is empty")
        return path

    @field_validator("git_url")
    @classmethod
    def _check_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        url = value.strip()
        if not GIT_URL_RE.fullmatch(url) or url.startswith("-"):
            raise ValueError("git_url must be an https://, ssh://, git:// or user@host:path address")
        return url

    @model_validator(mode="after")
    def _one_source(self) -> "ProjectCreate":
        if (self.git_url is None) == (self.source_path is None):
            raise ValueError("give either source_path with source_target_id or git_url")
        if self.source_path is not None and not self.source_target_id:
            raise ValueError("source_target_id is required with source_path")
        return self


class ProjectPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    include_remotes: bool | None = None
    fetch_origin: bool | None = None
    default_base: str | None = Field(None, min_length=1, max_length=200)
    size_limit_mb: int | None = Field(None, ge=1, le=20480)
    file_limit_mb: int | None = Field(None, ge=1, le=2048)
    instructions: str | None = Field(None, max_length=INSTRUCTIONS_LIMIT)
    default_executor_id: str | None = Field(None, max_length=100)

    @field_validator("default_base")
    @classmethod
    def _check_base(cls, value: str | None) -> str | None:
        # "default" is the project's main branch as the device sees it.
        if value is not None and value != "default" and not BRANCH_RE.fullmatch(value):
            raise ValueError("default_base must be a branch name or default")
        return value


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
    git_url: str | None = None
    include_remotes: bool = True
    fetch_origin: bool = False
    size_limit_mb: int = 1024
    file_limit_mb: int = 100
    known: dict[str, str] = {}
    bundle: bool = False
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
    main: str | None = None
    bundle: BundleInfo | None = None
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
    bundle: BundleInfo | None = None
    signature: str = ""
