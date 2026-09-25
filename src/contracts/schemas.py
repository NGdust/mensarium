import json
from pathlib import Path

from pydantic import BaseModel

from mensarium.contracts import llm, plugins, protocol
from mensarium.contracts.tools import TOOL_ARGS

MODELS: dict[str, type[BaseModel]] = {
    "target.hello": protocol.TargetHello,
    "auth.challenge": protocol.AuthChallenge,
    "auth.response": protocol.AuthResponse,
    "target.heartbeat": protocol.Heartbeat,
    "execution.request": protocol.ExecutionRequest,
    "execution.cancel": protocol.ExecutionCancel,
    "execution.result": protocol.ExecutionResult,
    "target.update": protocol.TargetUpdate,
    "target.update.status": protocol.TargetUpdateStatus,
    "target.plugins": protocol.TargetPlugins,
    "target.plugins.status": protocol.TargetPluginsStatus,
    "pair.request": protocol.PairRequest,
    "pair.response": protocol.PairResponse,
    "llm.chat_request": llm.ChatRequest,
    "llm.model_response": llm.ModelResponse,
    "plugin.manifest": plugins.Plugin,
    **{f"tool.{name}": model for name, model in TOOL_ARGS.items()},
}


def export(out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, model in MODELS.items():
        path = out_dir / f"{name}.schema.json"
        path.write_text(json.dumps(model.model_json_schema(), indent=2, ensure_ascii=False) + "\n")
        written.append(path)
    return written
