from datetime import datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, model_validator

from mensarium.contracts.protocol import AccessMode
from mensarium.shared import cron

ScheduleKind = Literal["at", "every", "cron"]
RunStatus = Literal["running", "ok", "error", "timeout", "canceled", "lost"]
RunTrigger = Literal["schedule", "manual", "catchup"]

_KIND_FIELD = {"at": "at", "every": "every_s", "cron": "expr"}


class AutomationError(Exception):
    def __init__(self, message: str, code: int = 422) -> None:
        super().__init__(message)
        self.code = code


class Schedule(BaseModel):
    kind: ScheduleKind = Field(description="at: once at a moment; every: fixed interval; cron: 5-field expression")
    at: str | None = Field(None, description="ISO 8601 datetime with a UTC offset, e.g. 2026-10-01T09:00:00+03:00")
    every_s: int | None = Field(None, ge=60, le=366 * 86_400, description="interval in seconds, at least 60")
    expr: str | None = Field(None, description="5 fields: minute hour day-of-month month day-of-week, e.g. `0 9 * * 1-5`")
    tz: str = Field(description="IANA timezone name, e.g. Europe/Moscow")

    @model_validator(mode="after")
    def _check(self) -> "Schedule":
        try:
            ZoneInfo(self.tz)
        except ZoneInfoNotFoundError as e:
            raise ValueError(f"unknown timezone {self.tz!r}") from e
        values = {"at": self.at, "every_s": self.every_s, "expr": self.expr}
        wanted = _KIND_FIELD[self.kind]
        if values[wanted] is None:
            raise ValueError(f"{wanted} is required for kind {self.kind!r}")
        for name, value in values.items():
            if name != wanted and value is not None:
                raise ValueError(f"{name} is not allowed for kind {self.kind!r}")
        if self.kind == "at":
            assert self.at is not None
            if datetime.fromisoformat(self.at).tzinfo is None:
                raise ValueError("the time must include a timezone offset")
        elif self.kind == "cron":
            assert self.expr is not None
            try:
                cron.parse(self.expr)
            except cron.CronError as e:
                raise ValueError(str(e)) from e
        return self

    def text(self) -> str:
        if self.kind == "every":
            assert self.every_s is not None
            if self.every_s % 60:
                return f"every {self.every_s} s"
            if self.every_s < 3600 or self.every_s % 3600:
                return f"every {self.every_s // 60} min"
            return f"every {self.every_s // 3600} h"
        if self.kind == "at":
            assert self.at is not None
            dt = datetime.fromisoformat(self.at).astimezone(ZoneInfo(self.tz))
            return f"once at {dt.strftime('%Y-%m-%d %H:%M')} ({self.tz})"
        return f"cron {self.expr} ({self.tz})"


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    prompt: str = Field(min_length=1, max_length=20_000)
    schedule: Schedule
    target_id: str
    mode: AccessMode = "ask"
    model: str | None = None
    timeout_s: int = Field(3600, ge=60, le=86_400)
    notify: bool = True
    delete_after_run: bool = False
    enabled: bool = True


class AutomationPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    prompt: str | None = Field(None, min_length=1, max_length=20_000)
    schedule: Schedule | None = None
    target_id: str | None = None
    mode: AccessMode | None = None
    model: str | None = None
    timeout_s: int | None = Field(None, ge=60, le=86_400)
    notify: bool | None = None
    delete_after_run: bool | None = None
    enabled: bool | None = None
