from typing import Any, Literal

from pydantic import BaseModel, Field

from mensarium.shared.crypto import canonical_json, sha256_hex

PROTOCOL_VERSION = "1.0"

ExecStatus = Literal["succeeded", "failed", "timeout", "canceled", "rejected"]


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


class Capabilities(BaseModel):
    tools: list[str]
    shells: list[str] = []
    sandbox_modes: list[str] = ["workspace-only"]
    browser: dict[str, bool] = {"playwright": False}
    limits: TargetLimits = TargetLimits()


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
    signature: str = ""


class ExecutionCancel(BaseModel):
    type: Literal["execution.cancel"] = "execution.cancel"
    request_id: str
    target_id: str
    issued_at: str
    signature: str = ""


class ToolOutput(BaseModel):
    exit_code: int | None = None
    stdout: str = ""
    stderr: str = ""
    truncated: bool = False
    artifacts: list[str] = []


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
    return sha256_hex(canonical_json({"target": policy.model_dump(), "tools": sorted(tools)}))
