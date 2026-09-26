"""Frames of the gateway tunnel: a client's gateway session relays browser HTTP requests to the Core."""

from typing import Literal

from pydantic import BaseModel, Field

SessionKind = Literal["worker", "gateway"]

GATEWAY_SCOPE_KEY = "mensarium.gateway"
MAX_REQUEST_BODY = 16 * 1024 * 1024
REQUEST_HEADERS = ("content-type", "accept", "last-event-id")
RESPONSE_HEADERS = ("content-type", "content-disposition", "cache-control")


class ApiRequest(BaseModel):
    type: Literal["api.request"] = "api.request"
    id: str
    method: str
    path: str
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""


class ApiResponse(BaseModel):
    type: Literal["api.response"] = "api.response"
    id: str
    status: int
    headers: dict[str, str] = Field(default_factory=dict)
    body: str = ""
    stream: bool = False


class ApiChunk(BaseModel):
    type: Literal["api.chunk"] = "api.chunk"
    id: str
    body: str


class ApiEnd(BaseModel):
    type: Literal["api.end"] = "api.end"
    id: str
    error: str | None = None


class ApiCancel(BaseModel):
    type: Literal["api.cancel"] = "api.cancel"
    id: str
