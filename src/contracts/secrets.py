from pydantic import BaseModel, Field

SECRET_NAME = r"^[A-Z][A-Z0-9_]{1,63}$"
RESERVED_NAMES = {"PATH", "HOME", "USER", "SHELL", "PWD", "LANG", "TMPDIR"}
RESERVED_PREFIXES = ("LC_", "MENSARIUM_")
MAX_SECRET_BYTES = 16 * 1024


class SecretInfo(BaseModel):
    name: str
    description: str = ""
    targets: list[str] = ["*"]
    created_at: str
    updated_at: str


class SecretPut(BaseModel):
    value: str | None = Field(None, max_length=MAX_SECRET_BYTES)
    description: str = Field("", max_length=300)
    targets: list[str] = Field(default_factory=lambda: ["*"], min_length=1, max_length=50)


class SecretRequestAnswer(BaseModel):
    value: str | None = Field(None, max_length=MAX_SECRET_BYTES)
    description: str | None = Field(None, max_length=300)
    targets: list[str] | None = Field(None, min_length=1, max_length=50)
    declined: bool = False
