from importlib import resources

import yaml
from pydantic import BaseModel, Field


class ProfileLLM(BaseModel):
    model: str | None = None
    temperature: float = 0.1
    max_output_tokens: int = 2000
    max_context_tokens: int = 12000


class ProfileLimits(BaseModel):
    max_steps: int = 30
    max_tool_calls: int = 30
    max_output_chars: int = 24000
    max_wall_time_s: int = 1800


class ProfileApproval(BaseModel):
    required_risks: list[str] = ["write", "execute", "network", "destructive"]


class AgentProfile(BaseModel):
    id: str
    name: str
    version: str
    instructions_ref: str | None = None
    instructions: str = ""
    llm: ProfileLLM = Field(default_factory=ProfileLLM)
    allowed_targets: list[str] = ["darwin", "linux"]
    allowed_tools: list[str]
    allow_extensions: bool = False
    default_mode: str = "propose_then_execute"
    limits: ProfileLimits = Field(default_factory=ProfileLimits)
    approval: ProfileApproval = Field(default_factory=ProfileApproval)


def builtin_profiles() -> list[AgentProfile]:
    pkg = resources.files("mensarium.profiles")
    out = []
    for f in pkg.iterdir():
        if f.name.endswith(".yaml"):
            profile = AgentProfile.model_validate(yaml.safe_load(f.read_text()))
            if profile.instructions_ref and not profile.instructions:
                profile.instructions = (pkg / profile.instructions_ref).read_text()
            out.append(profile)
    return out
