from typing import Literal

from pydantic import BaseModel

from mensarium.contracts.protocol import AccessMode

ChannelState = Literal["off", "connecting", "waiting_owner", "ready", "error"]


class TelegramBot(BaseModel):
    id: int
    username: str = ""
    name: str = ""


class TelegramOwner(BaseModel):
    user_id: int
    name: str = ""
    username: str | None = None
    bound_at: str


class TelegramConfig(BaseModel):
    enabled: bool = True
    bot: TelegramBot | None = None
    owner: TelegramOwner | None = None
    target_id: str | None = None
    mode: AccessMode = "ask"
    task_id: str | None = None
