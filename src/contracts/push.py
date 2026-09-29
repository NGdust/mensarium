from pydantic import BaseModel


class PushSubscription(BaseModel):
    endpoint: str
    p256dh: str
    auth: str
    lang: str = "en"
    agent: str = ""
    created_at: str


class PushConfig(BaseModel):
    approvals: bool = True
    finished: bool = True
    subscriptions: list[PushSubscription] = []
