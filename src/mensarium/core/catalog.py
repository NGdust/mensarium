import logging
import time

import httpx
from pydantic import ValidationError

from mensarium.contracts.plugins import Plugin
from mensarium.plugins import bundled_catalog
from mensarium.shared.versions import parse_version

log = logging.getLogger(__name__)

CATALOG_TTL_S = 900


class Catalog:
    """Bundled packages merged with the catalog published on mensarium.com (newer versions win)."""

    def __init__(self, url: str | None) -> None:
        self.url = url
        self._remote: tuple[float, list[Plugin], str | None] | None = None

    async def load(self) -> tuple[dict[str, Plugin], str | None]:
        merged = {e.id: e for e in bundled_catalog()}
        remote, error = await self._fetch()
        for e in remote:
            if e.id not in merged or parse_version(e.version) > parse_version(merged[e.id].version):
                merged[e.id] = e
        return merged, error

    async def _fetch(self) -> tuple[list[Plugin], str | None]:
        if not self.url:
            return [], None
        if self._remote and time.monotonic() - self._remote[0] < CATALOG_TTL_S:
            return self._remote[1], self._remote[2]
        items: list[Plugin] = []
        error = None
        try:
            async with httpx.AsyncClient(timeout=6, follow_redirects=True) as client:
                resp = await client.get(self.url)
                resp.raise_for_status()
                for raw in resp.json().get("plugins", []):
                    try:
                        items.append(Plugin.model_validate(raw))
                    except ValidationError:
                        log.warning("skipped invalid catalog entry", extra={"id": raw.get("id")})
        except (httpx.HTTPError, ValueError, AttributeError) as e:
            error = f"catalog {self.url} is unavailable: {e}"
        self._remote = (time.monotonic(), items, error)
        return items, error
