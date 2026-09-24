import posixpath
import shlex
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from mensarium.contracts.protocol import TargetPolicy
from mensarium.contracts.tools import PATH_FIELDS
from mensarium.shared.redaction import is_secret_path
from mensarium.tool_runtime.registry import REGISTRY, Risk

RISK_ORDER: list[Risk] = ["read", "execute", "write", "network", "destructive", "privileged"]
PRIVILEGED_PROGRAMS = {"sudo", "su", "doas", "pkexec", "security", "launchctl", "systemctl", "chown"}
SHELL_OPERATORS = {"|", "||", "&&", ";", ">", ">>", "<", "<<", "&", "2>", "2>&1"}
NETWORK_PROGRAMS = {"curl", "wget", "ssh", "scp", "rsync", "nc", "ncat", "telnet", "ftp", "brew"}
NETWORK_SUBCOMMANDS = {
    "git": {"push", "pull", "fetch", "clone", "remote", "submodule"},
    "pip": {"install", "download"},
    "pip3": {"install", "download"},
    "uv": {"add", "sync", "pip", "lock", "tool"},
    "npm": {"install", "i", "ci", "publish", "add"},
    "pnpm": {"install", "i", "add", "publish"},
    "yarn": {"install", "add", "publish"},
    "poetry": {"install", "add", "update", "publish"},
    "cargo": {"install", "publish", "fetch"},
    "go": {"get", "install"},
    "docker": {"pull", "push", "login", "run"},
}
DESTRUCTIVE_PROGRAMS = {"rm", "rmdir", "dd", "mkfs", "shred", "kill", "killall", "pkill", "truncate"}
DESTRUCTIVE_GIT = {("reset", "--hard"), ("clean", ""), ("push", "--force"), ("push", "-f"), ("checkout", "--")}
WRITE_PROGRAMS = {"mv", "cp", "touch", "mkdir", "tee", "patch", "ln", "chmod"}
WRITE_GIT = {"apply", "add", "commit", "checkout", "switch", "restore", "stash", "merge", "rebase", "mv", "rm"}


@dataclass
class Decision:
    allowed: bool
    reason: str = ""
    risk: Risk = "read"
    requires_approval: bool = False
    arguments: dict[str, Any] = field(default_factory=dict)
    display: str = ""


def _deny(reason: str, risk: Risk = "read") -> Decision:
    return Decision(allowed=False, reason=reason, risk=risk)


def _within(path: str, root: str) -> bool:
    root = root.rstrip("/") or "/"
    return path == root or path.startswith(root + "/") or root == "/"


def _normalize_path(value: str, roots: list[str]) -> str:
    if value.startswith("~"):
        raise ValueError(f"path {value!r}: use an absolute path or a path relative to {roots[0]}")
    full = value if value.startswith("/") else posixpath.join(roots[0], value)
    full = posixpath.normpath(full)
    if not any(_within(full, r) for r in roots):
        raise ValueError(f"path {full!r} is outside allowed roots {roots}")
    return full


def classify_command(argv: list[str]) -> Risk:
    program = posixpath.basename(argv[0])
    args = argv[1:]
    sub = args[0] if args else ""
    if program in PRIVILEGED_PROGRAMS:
        return "privileged"
    if program in DESTRUCTIVE_PROGRAMS:
        return "destructive"
    if program == "git":
        for s, flag in DESTRUCTIVE_GIT:
            if sub == s and (flag == "" or flag in args):
                return "destructive"
    if program in NETWORK_PROGRAMS or sub in NETWORK_SUBCOMMANDS.get(program, set()):
        return "network"
    if program in WRITE_PROGRAMS or (program == "git" and sub in WRITE_GIT):
        return "write"
    if program == "sed" and any(a.startswith("-i") for a in args):
        return "write"
    return "execute"


def evaluate(
    tool: str,
    raw_args: dict[str, Any] | None,
    *,
    profile_tools: list[str],
    required_risks: list[str],
    target_tools: list[str],
    target_policy: TargetPolicy,
    disabled_tools: list[str] | None = None,
) -> Decision:
    spec = REGISTRY.get(tool)
    if spec is None:
        return _deny(f"unknown tool {tool!r}")
    if tool not in profile_tools:
        return _deny(f"tool {tool!r} is not allowed by the active profile")
    if tool in (disabled_tools or []):
        return _deny(f"tool {tool!r} is disabled for this device")
    if tool not in target_tools:
        return _deny(f"target does not support tool {tool!r}")
    if raw_args is None:
        return _deny("arguments are not valid JSON")
    try:
        args = spec.args_model.model_validate(raw_args).model_dump()
    except ValidationError as e:
        return _deny(f"invalid arguments: {e.errors(include_url=False)}")
    if not target_policy.roots:
        return _deny("target has no allowed roots")
    try:
        for f in PATH_FIELDS.get(tool, ()):
            if args.get(f) is not None:
                args[f] = _normalize_path(args[f], target_policy.roots)
    except ValueError as e:
        return _deny(str(e))

    risk: Risk = spec.risk
    if tool in ("files.read", "files.list", "files.search") and is_secret_path(args["path"]):
        return _deny("access to secret files is not allowed")
    if tool == "shell.exec":
        try:
            argv = shlex.split(args["command"])
        except ValueError as e:
            return _deny(f"cannot parse command: {e}")
        if not argv:
            return _deny("empty command")
        if ops := [a for a in argv if a in SHELL_OPERATORS]:
            return _deny(f"shell operators {ops} are not supported: commands run without a shell")
        program = posixpath.basename(argv[0])
        if program == "cd":
            return _deny("`cd` is not supported; pass the directory in `cwd`")
        allow = target_policy.command_allowlist
        if "*" not in allow and "/" in argv[0]:
            return _deny("run programs by name, not by path")
        if "*" not in allow and program not in allow:
            return _deny(f"program {program!r} is not in the target command allowlist")
        risk = max(classify_command(argv), risk, key=RISK_ORDER.index)
    if risk == "privileged":
        return _deny("privileged actions are denied", risk)

    return Decision(
        allowed=True,
        risk=risk,
        requires_approval=risk in required_risks,
        arguments=args,
        display=spec.display(args),
    )
