import os
from pathlib import Path


def mensarium_home() -> Path:
    return Path(os.environ.get("MENSARIUM_HOME", Path.home() / ".mensarium")).expanduser()


def core_dir() -> Path:
    return mensarium_home() / "core"


def client_dir() -> Path:
    """The client's data directory; a pre-0.38 `target/` directory is moved here on first access."""
    new, old = mensarium_home() / "client", mensarium_home() / "target"
    if not new.exists() and old.exists():
        old.rename(new)
        legacy_key = new / "keys" / "target_ed25519.pem"
        if legacy_key.exists():
            legacy_key.rename(new / "keys" / "client_ed25519.pem")
    return new


def ensure_private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def write_private(path: Path, content: str | bytes) -> None:
    ensure_private_dir(path.parent)
    data = content.encode() if isinstance(content, str) else content
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    path.chmod(0o600)
