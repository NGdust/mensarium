from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from mensarium.shared.paths import core_dir, ensure_private_dir, write_private


class ServerConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8787
    public_url: str = "http://127.0.0.1:8787"


class ProviderConfig(BaseModel):
    base_url: str
    default_model: str
    api_key_ref: str | None = None
    timeout_s: int = 90
    max_retries: int = 2


class LLMConfig(BaseModel):
    active_provider: str = "ollama_cloud"
    providers: dict[str, ProviderConfig] = Field(default_factory=dict)


class ExecutionConfig(BaseModel):
    approval_ttl_s: int = 900
    request_ttl_s: int = 120


class LocalTargetConfig(BaseModel):
    enabled: bool = True
    roots: list[str] = Field(default_factory=lambda: ["~"])
    allow_full_access: bool = True


class PluginsConfig(BaseModel):
    catalog_url: str | None = "https://mensarium.com/dist/plugins.json"


class CoreConfig(BaseModel):
    update_url: str = "https://mensarium.com"
    server: ServerConfig = Field(default_factory=ServerConfig)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)
    local_target: LocalTargetConfig = Field(default_factory=LocalTargetConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    log_level: str = "INFO"


class CorePaths:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or core_dir()
        self.config = self.root / "config.yaml"
        self.db = self.root / "mensarium.db"
        self.secrets = self.root / "secrets"
        self.keys = self.root / "keys"
        self.signing_key = self.keys / "core_ed25519.pem"
        self.artifacts = self.root / "artifacts"
        self.logs = self.root / "logs"

    def ensure(self) -> None:
        ensure_private_dir(self.root)
        for d in (self.secrets, self.keys, self.artifacts, self.logs):
            ensure_private_dir(d)


def load_config(paths: CorePaths) -> CoreConfig:
    if not paths.config.exists():
        raise FileNotFoundError(f"Core is not configured: {paths.config} not found. Run `mensarium setup`.")
    return CoreConfig.model_validate(yaml.safe_load(paths.config.read_text()) or {})


def save_config(paths: CorePaths, cfg: CoreConfig) -> None:
    write_private(paths.config, yaml.safe_dump(cfg.model_dump(), sort_keys=False, allow_unicode=True))


def read_secret(paths: CorePaths, ref: str | None) -> str | None:
    if not ref:
        return None
    if not ref.startswith("secret://"):
        raise ValueError(f"secret reference must look like secret://name, got {ref!r}")
    f = paths.secrets / ref.removeprefix("secret://")
    return f.read_text().strip() if f.exists() else None


def write_secret(paths: CorePaths, name: str, value: str) -> str:
    write_private(paths.secrets / name, value)
    return f"secret://{name}"
