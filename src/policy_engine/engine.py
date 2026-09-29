import posixpath
import re
import shlex
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from mensarium.contracts.protocol import AccessMode, TargetPolicy
from mensarium.contracts.tools import PATH_FIELDS, WRITE_PATH_TOOLS
from mensarium.shared.redaction import GIT_DIRS, is_secret_path
from mensarium.shared.secret_refs import secret_refs
from mensarium.tool_runtime.commands import render
from mensarium.tool_runtime.mcp import check_arguments
from mensarium.tool_runtime.registry import REGISTRY, Risk, ToolSpec

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
    exec_tool: str = ""
    runs_on: str = "target"
    secrets: list[str] = field(default_factory=list)


def _deny(reason: str, risk: Risk = "read") -> Decision:
    return Decision(allowed=False, reason=reason, risk=risk)


def _within(path: str, root: str) -> bool:
    root = root.rstrip("/") or "/"
    return path == root or path.startswith(root + "/") or root == "/"


def _normalize_path(value: str, roots: list[str], base: str | None = None) -> str:
    base = base or roots[0]
    if value.startswith("~"):
        raise ValueError(f"path {value!r}: use an absolute path or a path relative to {base}")
    full = value if value.startswith("/") else posixpath.join(base, value)
    full = posixpath.normpath(full)
    if not any(_within(full, r) for r in roots):
        raise ValueError(f"path {full!r} is outside allowed roots {roots}")
    return full


def _is_secret(path: str, projects_root: str | None) -> bool:
    if projects_root and _within(path, projects_root):
        rel = posixpath.relpath(path, projects_root)
        return any(part.lower() in GIT_DIRS for part in rel.split("/")) or is_secret_path(rel)
    return is_secret_path(path)


ENV_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
COMMAND_PREFIXES = {"env", "time", "nohup", "nice", "exec", "command", "builtin", "xargs", "timeout"}
PRIVILEGED_TOKENS = PRIVILEGED_PROGRAMS | {"visudo", "passwd", "dscl", "csrutil", "spctl"}


def classify_script(script: str) -> Risk:
    """Best-effort risk of a bash script: the highest risk of its simple commands, privileged tokens anywhere.

    The user reviews the script before it runs; this only decides how the approval is labelled and
    refuses obviously privileged actions."""
    try:
        tokens = shlex.split(script, comments=True, posix=True)
    except ValueError:
        tokens = script.replace("\n", " ").split()
    if any(posixpath.basename(t) in PRIVILEGED_TOKENS for t in tokens):
        return "privileged"
    risk: Risk = "execute"
    for line in re.split(r"[\n;]|&&|\|\||\||\$\(|`", script):
        try:
            argv = shlex.split(line, comments=True, posix=True)
        except ValueError:
            argv = line.split()
        while argv and (ENV_ASSIGNMENT.match(argv[0]) or posixpath.basename(argv[0]) in COMMAND_PREFIXES):
            argv = argv[1:]
        if any(a.startswith((">", "2>", "&>")) for a in argv):
            risk = max(risk, "write", key=RISK_ORDER.index)
        argv = [a for a in argv if a not in SHELL_OPERATORS and a not in ("(", ")", "{", "}")]
        if not argv:
            continue
        if posixpath.basename(argv[0]) == "find" and ("-delete" in argv or "rm" in argv):
            risk = max(risk, "destructive", key=RISK_ORDER.index)
        risk = max(risk, classify_command(argv), key=RISK_ORDER.index)
    return risk


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
    registry: Mapping[str, ToolSpec] = REGISTRY,
    workdir: str | None = None,
    projects_root: str | None = None,
    mode: AccessMode = "ask",
) -> Decision:
    """`arguments` and `exec_tool` of an allowed decision are what is sent to the device (or run in Core)."""
    spec = registry.get(tool)
    if spec is None:
        return _deny(f"unknown tool {tool!r}")
    if tool not in profile_tools:
        return _deny(f"tool {tool!r} is not allowed by the active profile")
    disabled = disabled_tools or []
    if tool in disabled:
        return _deny(f"tool {tool!r} is disabled for this device")
    if raw_args is None:
        return _deny("arguments are not valid JSON")
    try:
        args = spec.args_model.model_validate(raw_args).model_dump()
    except ValidationError as e:
        return _deny(f"invalid arguments: {e.errors(include_url=False)}")
    if spec.schema is not None and (problem := check_arguments(args, spec.schema)):
        return _deny(f"invalid arguments: {problem}")
    if spec.runs_on == "core":
        return Decision(
            allowed=True,
            risk=spec.risk,
            requires_approval=spec.risk in required_risks,
            arguments=args,
            display=spec.display(args),
            exec_tool=tool,
            runs_on="core",
        )

    unrestricted = mode == "full" and target_policy.allow_full_access
    exec_tool = tool
    if spec.mcp:
        exec_tool = "mcp.call"
        if exec_tool in disabled:
            return _deny(f"tool {tool!r} runs through mcp.call, which is disabled for this device")
        if exec_tool not in target_tools:
            return _deny(f"target does not support tool {exec_tool!r}")
        return Decision(
            allowed=True,
            risk=spec.risk,
            requires_approval=spec.risk in required_risks,
            arguments={"server": spec.mcp[0], "tool": spec.mcp[1], "arguments": args},
            display=spec.display(args),
            exec_tool=exec_tool,
        )
    if spec.command:
        try:
            args = render(spec.command, args)
        except ValueError as e:
            return _deny(f"invalid arguments: {e}")
        exec_tool = "shell.exec"
        if exec_tool in disabled:
            return _deny(f"tool {tool!r} runs through shell.exec, which is disabled for this device")
    if exec_tool not in target_tools:
        return _deny(f"target does not support tool {exec_tool!r}")
    roots = ["/"] if unrestricted else target_policy.roots
    base = workdir or (target_policy.roots[0] if target_policy.roots else "/")
    if not roots:
        return _deny("target has no allowed roots")
    try:
        for f in PATH_FIELDS.get(exec_tool, ()):
            if args.get(f) is not None:
                args[f] = _normalize_path(args[f], roots, base)
    except ValueError as e:
        return _deny(str(e))

    risk: Risk = spec.risk
    if not unrestricted and exec_tool in ("files.read", "files.list", "files.search", "files.stat", "files.find") and _is_secret(args["path"], projects_root):
        return _deny("access to secret files is not allowed")
    if not unrestricted and exec_tool in WRITE_PATH_TOOLS and any(_is_secret(args[f], projects_root) for f in PATH_FIELDS[exec_tool]):
        return _deny("secret files and folders cannot be changed by the agent")
    if exec_tool == "shell.bash":
        risk = max(classify_script(args["script"]), risk, key=RISK_ORDER.index)
    if exec_tool == "shell.exec":
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
        allow = ["*"] if unrestricted else target_policy.command_allowlist
        if "*" not in allow and "/" in argv[0]:
            return _deny("run programs by name, not by path")
        if "*" not in allow and program not in allow:
            return _deny(f"program {program!r} is not in the target command allowlist")
        risk = max(classify_command(argv), risk, REGISTRY["shell.exec"].risk, key=RISK_ORDER.index)
    if risk == "privileged" and not unrestricted:
        return _deny("privileged actions are denied", risk)

    return Decision(
        allowed=True,
        risk=risk,
        requires_approval=not unrestricted and risk in required_risks,
        arguments=args,
        display=spec.display(args),
        exec_tool=exec_tool,
        secrets=secret_refs(exec_tool, args),
    )
