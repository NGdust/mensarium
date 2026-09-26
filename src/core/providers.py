import os
import re
import shutil
from typing import Any

from mensarium.core.config import CoreConfig, CorePaths, ProviderConfig, read_secret, save_config, write_secret
from mensarium.llm_providers.base import LLMError
from mensarium.llm_providers.factory import PROVIDER_KINDS, AnyProvider, build_provider, is_cli
from mensarium.llm_providers.local_cli import detect_local_clis_cached
from mensarium.llm_providers.router import ProviderRouter

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,40}$")


class ProviderError(Exception):
    pass


class Providers:
    """LLM providers in the Core config: add, change, remove, keep the default one; keys live in Core secrets.
    `llm.active_provider` is the default: the provider of the model last picked for a new chat."""

    def __init__(self, cfg: CoreConfig, paths: CorePaths) -> None:
        self.cfg = cfg
        self.paths = paths
        self.router: ProviderRouter | None = None

    def _switch(self, pid: str) -> None:
        if not self.router:
            return
        if pid == self.cfg.llm.active_provider:
            self.router.swap(self.active_client())
        else:
            self.router.drop(pid)

    @staticmethod
    def kind(pid: str, p: ProviderConfig) -> str:
        return p.kind or pid

    def _client(self, pid: str, p: ProviderConfig, api_key: str | None = None) -> AnyProvider:
        return build_provider(
            pid,
            kind=self.kind(pid, p),
            base_url=p.base_url,
            default_model=p.default_model,
            api_key=api_key if api_key is not None else read_secret(self.paths, p.api_key_ref),
            timeout_s=p.timeout_s,
            max_retries=p.max_retries,
            vision_model=p.vision_model,
        )

    def active_client(self) -> AnyProvider:
        pid = self.cfg.llm.active_provider
        return self._client(pid, self.cfg.llm.providers[pid])

    def client(self, pid: str) -> AnyProvider:
        return self._client(pid, self.cfg.llm.providers[pid])

    def view(self) -> dict[str, Any]:
        providers = []
        for pid, p in self.cfg.llm.providers.items():
            kind = self.kind(pid, p)
            meta = PROVIDER_KINDS.get(kind, {})
            providers.append(
                {
                    "id": pid,
                    "kind": kind,
                    "title": meta.get("title", kind),
                    "base_url": p.base_url,
                    "default_model": p.default_model,
                    "vision_model": p.vision_model or "",
                    "has_key": bool(read_secret(self.paths, p.api_key_ref)),
                    "needs_key": bool(meta.get("needs_key")),
                    "transport": meta.get("transport", "http"),
                    "timeout_s": p.timeout_s,
                    "max_retries": p.max_retries,
                    "active": pid == self.cfg.llm.active_provider,
                }
            )
        kinds = [{"kind": k, "transport": "http", **v} for k, v in PROVIDER_KINDS.items()]
        return {"active": self.cfg.llm.active_provider, "providers": providers, "kinds": kinds}

    async def detected(self) -> list[dict[str, Any]]:
        """Local agent CLIs on this host that are not connected as a provider yet."""
        connected = {self.kind(pid, p) for pid, p in self.cfg.llm.providers.items()}
        return [cli.view() for cli in await detect_local_clis_cached() if cli.kind not in connected]

    def save(
        self,
        pid: str,
        *,
        kind: str,
        base_url: str,
        default_model: str,
        api_key: str | None,
        timeout_s: int,
        max_retries: int,
        vision_model: str | None = None,
    ) -> None:
        """`api_key` None keeps the stored key, "" deletes it."""
        if not ID_RE.match(pid):
            raise ProviderError("provider id: lowercase letters, digits, - and _")
        if kind not in PROVIDER_KINDS:
            raise ProviderError(f"unknown provider kind {kind!r}")
        if is_cli(kind):
            if not (shutil.which(base_url) or os.access(base_url, os.X_OK)):
                raise ProviderError(f"{base_url} is not an executable command on the Core host")
        elif not base_url.startswith(("http://", "https://")):
            raise ProviderError("the address must start with http:// or https://")
        if not default_model.strip():
            raise ProviderError("choose a default model")
        old = self.cfg.llm.providers.get(pid)
        ref = old.api_key_ref if old else None
        if api_key:
            ref = write_secret(self.paths, ref.removeprefix("secret://") if ref else f"provider-{pid}-key", api_key)
        elif api_key == "" and ref:
            (self.paths.secrets / ref.removeprefix("secret://")).unlink(missing_ok=True)
            ref = None
        if PROVIDER_KINDS[kind]["needs_key"] and not read_secret(self.paths, ref):
            raise ProviderError(f"{PROVIDER_KINDS[kind]['title']} needs an API key")
        self.cfg.llm.providers[pid] = ProviderConfig(
            kind=kind, base_url=base_url.rstrip("/"), default_model=default_model.strip(), api_key_ref=ref,
            timeout_s=timeout_s, max_retries=max_retries, vision_model=(vision_model or "").strip() or None,
        )
        if self.cfg.llm.active_provider not in self.cfg.llm.providers:
            self.cfg.llm.active_provider = pid
        save_config(self.paths, self.cfg)
        self._switch(pid)

    def remove(self, pid: str) -> None:
        if pid not in self.cfg.llm.providers:
            raise ProviderError("provider not found")
        if len(self.cfg.llm.providers) == 1:
            raise ProviderError("this is the only provider; add another one first")
        ref = self.cfg.llm.providers.pop(pid).api_key_ref
        if ref and not any(p.api_key_ref == ref for p in self.cfg.llm.providers.values()):
            (self.paths.secrets / ref.removeprefix("secret://")).unlink(missing_ok=True)
        if pid == self.cfg.llm.active_provider:
            self.cfg.llm.active_provider = next(iter(self.cfg.llm.providers))
            self._switch(self.cfg.llm.active_provider)
        save_config(self.paths, self.cfg)
        if self.router:
            self.router.drop(pid)

    def set_default(self, pid: str, model: str) -> None:
        """The model picked for a new chat becomes the default for the next chats and background work."""
        if pid not in self.cfg.llm.providers:
            raise ProviderError("provider not found")
        switched = pid != self.cfg.llm.active_provider
        self.cfg.llm.active_provider = pid
        self.cfg.llm.providers[pid].default_model = model
        save_config(self.paths, self.cfg)
        if switched:
            self._switch(pid)
        elif self.router:
            self.router.default_model = model

    async def test(self, kind: str, base_url: str, api_key: str | None, pid: str | None) -> list[str]:
        """List the models with these settings; an empty key means the key already saved for `pid`."""
        if kind not in PROVIDER_KINDS:
            raise ProviderError(f"unknown provider kind {kind!r}")
        if is_cli(kind):
            probe_cli = build_provider(pid or kind, kind=kind, base_url=base_url, default_model="", api_key=None, timeout_s=15, max_retries=0)
            health = await probe_cli.healthcheck()
            await probe_cli.aclose()
            if not health.ok:
                raise ProviderError(health.detail)
            return [m.id for m in await probe_cli.list_models()]
        stored = self.cfg.llm.providers.get(pid or "")
        key = api_key or (read_secret(self.paths, stored.api_key_ref) if stored else None)
        probe = ProviderConfig(kind=kind, base_url=base_url.rstrip("/"), default_model="", timeout_s=15, max_retries=0)
        client = self._client(pid or kind, probe, api_key=key or "")
        try:
            return sorted(m.id for m in await client.list_models())
        except LLMError as e:
            raise ProviderError(str(e)) from e
        finally:
            await client.aclose()
