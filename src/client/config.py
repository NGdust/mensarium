from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from mensarium.contracts.protocol import TargetLimits, TargetPolicy
from mensarium.shared.paths import client_dir, ensure_private_dir, write_private

DEFAULT_COMMAND_ALLOWLIST = [
    "git", "python", "python3", "pytest", "uv", "pip", "pip3", "poetry", "ruff", "mypy", "black",
    "node", "npm", "pnpm", "yarn", "go", "cargo", "make", "ls", "cat", "head", "tail", "wc", "grep", "rg",
    "find", "diff", "patch", "tree", "echo", "mkdir", "touch", "cp", "mv", "jq",
]  # fmt: skip


class WorkerConfig(BaseModel):
    enabled: bool = True


class GatewayConfig(BaseModel):
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8790
    allowed_hosts: list[str] = Field(default_factory=list)


class ClientConfig(BaseModel):
    server: str
    ws_url: str
    target_id: str
    workspace_id: str
    name: str
    core_public_key: str
    core_fingerprint: str
    roots: list[str]
    command_allowlist: list[str] = Field(default_factory=lambda: list(DEFAULT_COMMAND_ALLOWLIST))
    allow_full_access: bool = True
    allow_remote_update: bool = True
    allow_remote_plugins: bool = True
    allow_shell: bool = True
    limits: TargetLimits = Field(default_factory=TargetLimits)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    gateway: GatewayConfig = Field(default_factory=GatewayConfig)
    moved_to: str | None = None

    @property
    def policy(self) -> TargetPolicy:
        return TargetPolicy(
            roots=self.roots, command_allowlist=self.command_allowlist, allow_full_access=self.allow_full_access
        )


class ClientPaths:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or client_dir()
        self.config = self.root / "config.yaml"
        self.key = self.root / "keys" / "client_ed25519.pem"
        self.audit = self.root / "audit.jsonl"
        self.plugins = self.root / "plugins.json"
        self.permissions = self.root / "permissions.json"
        self.secrets = self.root / "secrets"
        self.gateway_token = self.secrets / "gateway-token"
        self.gateway_link = self.secrets / "gateway-link"
        self.backups = self.root / "backups"
        self.undo = self.root / "undo"

    def ensure(self) -> None:
        ensure_private_dir(self.root)
        ensure_private_dir(self.key.parent)


def load_client_config(paths: ClientPaths) -> ClientConfig:
    if not paths.config.exists():
        raise FileNotFoundError(f"client is not paired: {paths.config} not found. Run `mensarium client pair`.")
    return ClientConfig.model_validate(yaml.safe_load(paths.config.read_text()))


def save_client_config(paths: ClientPaths, cfg: ClientConfig) -> None:
    write_private(paths.config, yaml.safe_dump(cfg.model_dump(), sort_keys=False, allow_unicode=True))
