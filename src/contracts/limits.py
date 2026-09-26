"""Usage limits of an LLM provider as the UI shows them: one bar per window."""

from pydantic import BaseModel, Field

WARN_THRESHOLD = 0.75


class LimitWindow(BaseModel):
    label: str
    model: str | None = None
    used_percent: float = Field(ge=0)
    resets_at: str | None = None
    detail: str = ""


class ProviderLimits(BaseModel):
    provider_id: str
    title: str
    kind: str
    active: bool = False
    supported: bool = True
    source: str = ""
    checked_at: str | None = None
    windows: list[LimitWindow] = Field(default_factory=list)
    error: str | None = None
    note: str = ""

    @property
    def max_used(self) -> float:
        return max((w.used_percent for w in self.windows), default=0.0)
