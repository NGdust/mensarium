from mensarium.llm_providers.openai_compat import OpenAICompatibleProvider

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "ollama_cloud": {"base_url": "https://ollama.com/v1", "default_model": "gpt-oss:120b"},
    "ollama_local": {"base_url": "http://127.0.0.1:11434/v1", "default_model": "qwen3:8b"},
    "llama_cpp": {"base_url": "http://127.0.0.1:8080/v1", "default_model": "local"},
}


def build_provider(
    name: str,
    *,
    base_url: str,
    default_model: str,
    api_key: str | None,
    timeout_s: int,
    max_retries: int,
) -> OpenAICompatibleProvider:
    if name not in PROVIDER_DEFAULTS:
        raise ValueError(f"unknown LLM provider {name!r}")
    return OpenAICompatibleProvider(
        name=name,
        base_url=base_url,
        default_model=default_model,
        api_key=api_key,
        timeout_s=timeout_s,
        max_retries=max_retries,
    )
