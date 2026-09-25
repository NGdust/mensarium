from mensarium.llm_providers.openai_compat import OpenAICompatibleProvider

# All of them speak the OpenAI-compatible /v1 API; the kind only sets defaults and whether a key is needed.
PROVIDER_KINDS: dict[str, dict[str, str | bool]] = {
    "ollama_cloud": {"title": "Ollama Cloud", "base_url": "https://ollama.com/v1", "default_model": "gpt-oss:120b", "needs_key": True, "key_url": "https://ollama.com/settings/keys"},
    "ollama_local": {"title": "Ollama", "base_url": "http://127.0.0.1:11434/v1", "default_model": "qwen3:8b", "needs_key": False, "key_url": ""},
    "llama_cpp": {"title": "llama.cpp", "base_url": "http://127.0.0.1:8080/v1", "default_model": "local", "needs_key": False, "key_url": ""},
    "lmstudio": {"title": "LM Studio", "base_url": "http://127.0.0.1:1234/v1", "default_model": "local", "needs_key": False, "key_url": ""},
    "openai": {"title": "OpenAI", "base_url": "https://api.openai.com/v1", "default_model": "gpt-4.1-mini", "needs_key": True, "key_url": "https://platform.openai.com/api-keys"},
    "openrouter": {"title": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "default_model": "openai/gpt-oss-120b", "needs_key": True, "key_url": "https://openrouter.ai/keys"},
    "openai_compatible": {"title": "OpenAI-compatible", "base_url": "http://127.0.0.1:8000/v1", "default_model": "", "needs_key": False, "key_url": ""},
}
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    kind: {"base_url": str(v["base_url"]), "default_model": str(v["default_model"])} for kind, v in PROVIDER_KINDS.items()
}


def build_provider(
    name: str,
    *,
    base_url: str,
    default_model: str,
    api_key: str | None,
    timeout_s: int,
    max_retries: int,
    kind: str | None = None,
) -> OpenAICompatibleProvider:
    if (kind or name) not in PROVIDER_KINDS:
        raise ValueError(f"unknown LLM provider kind {kind or name!r}")
    return OpenAICompatibleProvider(
        name=name,
        base_url=base_url,
        default_model=default_model,
        api_key=api_key,
        timeout_s=timeout_s,
        max_retries=max_retries,
    )
