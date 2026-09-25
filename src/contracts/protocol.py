from typing import Any, Literal

from pydantic import BaseModel, Field

from mensarium.shared.crypto import canonical_json, sha256_hex

PROTOCOL_VERSION = "1.0"

ExecStatus = Literal["succeeded", "failed", "timeout", "canceled", "rejected"]
AccessMode = Literal["ask", "full"]


class TargetInfo(BaseModel):
    id: str
    name: str
    platform: str
    hostname: str
    agent_version: str


class TargetLimits(BaseModel):
    max_exec_seconds: int = 300
    max_stdout_bytes: int = 1_048_576
    max_artifact_bytes: int = 26_214_400


class TargetPolicy(BaseModel):
    roots: list[str]
    command_allowlist: list[str]
    allow_full_access: bool = False


class Capabilities(BaseModel):
    tools: list[str]
    shells: list[str] = []
    desktop: dict[str, bool | None] = {}
    sandbox_modes: list[str] = ["workspace-only"]
    browser: dict[str, bool] = {"playwright": False}
    limits: TargetLimits = TargetLimits()
    remote_update: bool = False


class TargetHello(BaseModel):
    type: Literal["target.hello"] = "target.hello"
    protocol_version: str = PROTOCOL_VERSION
    target: TargetInfo
    capabilities: Capabilities
    policy: TargetPolicy


class AuthChallenge(BaseModel):
    type: Literal["auth.challenge"] = "auth.challenge"
    nonce: str


class AuthResponse(BaseModel):
    type: Literal["auth.response"] = "auth.response"
    target_id: str
    nonce: str
    signature: str = ""


class Heartbeat(BaseModel):
    type: Literal["target.heartbeat"] = "target.heartbeat"
    ts: str


class ExecutionRequest(BaseModel):
    type: Literal["execution.request"] = "execution.request"
    request_id: str
    trace_id: str
    workspace_id: str
    task_id: str
    target_id: str
    tool_call_id: str
    issued_at: str
    expires_at: str
    nonce: str
    policy_snapshot_hash: str
    tool: str
    arguments: dict[str, Any]
    approval_ref: str | None = None
    mode: AccessMode = "ask"
    signature: str = ""


class ExecutionCancel(BaseModel):
    type: Literal["execution.cancel"] = "execution.cancel"
    request_id: str
    target_id: str
    issued_at: str
    signature: str = ""


class TargetUpdate(BaseModel):
    """Core asks a device to update its agent from the Core it is paired with."""

    type: Literal["target.update"] = "target.update"
    request_id: str
    target_id: str
    version: str
    issued_at: str
    expires_at: str
    nonce: str
    signature: str = ""


class TargetUpdateStatus(BaseModel):
    type: Literal["target.update.status"] = "target.update.status"
    request_id: str
    status: Literal["started", "rejected", "failed"]
    detail: str = ""
    signature: str = ""


class McpServerDef(BaseModel):
    """An MCP server the Core asks a device to run; config values are filled in, Core secrets never are."""

    name: str
    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = None
    args: list[str] = []
    env: dict[str, str] = {}
    url: str | None = None
    headers: dict[str, str] = {}
    risk: str = "network"
    cwd: str | None = None


class TargetPlugins(BaseModel):
    type: Literal["target.plugins"] = "target.plugins"
    request_id: str
    target_id: str
    issued_at: str
    expires_at: str
    nonce: str
    servers: list[McpServerDef] = []
    signature: str = ""


class McpToolInfo(BaseModel):
    name: str
    description: str = ""
    input_schema: dict[str, Any] = {}
    annotations: dict[str, Any] = {}


class McpServerStatus(BaseModel):
    name: str
    state: Literal["ok", "error", "rejected"]
    error: str = ""
    tools: list[McpToolInfo] = []


class TargetPluginsStatus(BaseModel):
    type: Literal["target.plugins.status"] = "target.plugins.status"
    request_id: str
    servers: list[McpServerStatus] = []
    signature: str = ""


class ToolOutput(BaseModel):
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    artifacts: list[str] = []
    images: list[dict[str, Any]] = Field(default_factory=list, description="Screenshots: {mime, data (base64), width, height}")


class ExecutionResult(BaseModel):
    type: Literal["execution.result"] = "execution.result"
    request_id: str
    tool_call_id: str
    status: ExecStatus
    started_at: str
    finished_at: str
    result: ToolOutput = Field(default_factory=ToolOutput)
    error: str | None = None
    target_audit_hash: str = ""
    signature: str = ""


class PairRequest(BaseModel):
    code: str
    name: str
    platform: str
    hostname: str
    agent_version: str
    public_key: str


class PairResponse(BaseModel):
    target_id: str
    workspace_id: str
    core_public_key: str
    core_fingerprint: str
    ws_url: str


def policy_snapshot_hash(policy: TargetPolicy, tools: list[str]) -> str:
    """Hash of the target policy the Core decided against; the target recomputes it from its own config."""
    # exclude_defaults keeps the hash identical for targets that predate optional policy fields
    return sha256_hex(canonical_json({"target": policy.model_dump(exclude_defaults=True), "tools": sorted(tools)}))
