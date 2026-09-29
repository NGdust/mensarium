"""User secrets: values as files in the Core secrets folder, names and device lists in kv."""

import asyncio
import re
from typing import Any

from mensarium.contracts.secrets import RESERVED_NAMES, RESERVED_PREFIXES, SECRET_NAME, SecretInfo
from mensarium.core.config import CorePaths, read_secret, write_secret
from mensarium.core.repo import Repo
from mensarium.shared.secret_refs import MIN_MASKED
from mensarium.shared.timeutil import now_iso

KEY = "secrets.user"
FILE_PREFIX = "user-"


class SecretError(Exception):
    pass


def check_name(name: str) -> None:
    if not re.match(SECRET_NAME, name) or name in RESERVED_NAMES or name.startswith(RESERVED_PREFIXES):
        raise SecretError(f"invalid secret name {name!r}: use UPPER_SNAKE_CASE that is not a system variable")


class SecretStore:
    def __init__(self, paths: CorePaths, repo: Repo) -> None:
        self.paths = paths
        self.repo = repo
        self.lock = asyncio.Lock()

    async def _meta(self) -> dict[str, dict[str, Any]]:
        return dict(await self.repo.get_setting(KEY) or {})

    async def all(self) -> list[SecretInfo]:
        return [SecretInfo(name=n, **m) for n, m in sorted((await self._meta()).items())]

    async def available(self, target_id: str) -> list[SecretInfo]:
        return [s for s in await self.all() if "*" in s.targets or target_id in s.targets]

    async def put(self, name: str, value: str | None, description: str, targets: list[str]) -> SecretInfo:
        check_name(name)
        value = (value or "").strip() or None
        async with self.lock:
            meta = await self._meta()
            old = meta.get(name)
            if value is None and old is None:
                raise SecretError("a new secret needs a value")
            if value is not None and len(value) < MIN_MASKED:
                raise SecretError("a secret value must be at least 4 characters")
            if value is not None:
                write_secret(self.paths, FILE_PREFIX + name, value)
            now = now_iso()
            meta[name] = {
                "description": description.strip(),
                "targets": targets or ["*"],
                "created_at": old["created_at"] if old else now,
                "updated_at": now,
            }
            await self.repo.set_setting(KEY, meta)
        return SecretInfo(name=name, **meta[name])

    async def delete(self, name: str) -> None:
        async with self.lock:
            meta = await self._meta()
            if meta.pop(name, None) is None:
                raise SecretError(f"secret {name} not found")
            await self.repo.set_setting(KEY, meta)
            (self.paths.secrets / (FILE_PREFIX + name)).unlink(missing_ok=True)

    async def resolve(self, names: list[str], target_id: str) -> dict[str, str]:
        meta = await self._meta()
        values: dict[str, str] = {}
        for name in dict.fromkeys(names):
            m = meta.get(name)
            if m is None:
                raise SecretError(f"secret {name} is not defined; ask the user to add it with secrets.request")
            if "*" not in m["targets"] and target_id not in m["targets"]:
                raise SecretError(f"secret {name} is not allowed on this device")
            value = read_secret(self.paths, f"secret://{FILE_PREFIX}{name}")
            if not value:
                raise SecretError(f"secret {name} has no value; ask the user to set it again")
            values[name] = value
        return values
