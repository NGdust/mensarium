import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from mensarium.contracts.llm import ModelResponse
from mensarium.llm_providers import cli_provider, local_cli
from mensarium.llm_providers.openai_compat import OpenAICompatibleProvider


class OpenAICompatibleWindowTests(unittest.IsolatedAsyncioTestCase):
    def make_provider(self, kind, base_url, handler, default_model="m"):
        p = OpenAICompatibleProvider("test", base_url, default_model, kind=kind)
        p._client = httpx.AsyncClient(base_url=p.base_url, transport=httpx.MockTransport(handler))
        self.addAsyncCleanup(p.aclose)
        return p

    async def test_ollama_cloud_context_window(self):
        bodies = []

        def handle(request):
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"model_info": {"gptoss.context_length": 131072, "general.architecture": "gptoss"}})

        p = self.make_provider("ollama_cloud", "https://ollama.com/v1", handle)
        self.assertEqual(await p.context_window("gpt-oss:120b"), 131072)
        self.assertEqual(bodies[0], {"model": "gpt-oss:120b"})

    async def test_ollama_local_context_window(self):
        def handle(request):
            return httpx.Response(200, json={"models": [{"name": "qwen3:8b", "model": "qwen3:8b", "context_length": 8192}]})

        p = self.make_provider("ollama_local", "http://127.0.0.1:11434/v1", handle)
        self.assertEqual(await p.context_window("qwen3:8b"), 8192)
        self.assertIsNone(await p.context_window("other-model"))

    async def test_llama_cpp_context_window(self):
        def handle(request):
            return httpx.Response(200, json={"default_generation_settings": {"n_ctx": 4096}})

        p = self.make_provider("llama_cpp", "http://127.0.0.1:8080/v1", handle)
        self.assertEqual(await p.context_window("m"), 4096)

    async def test_lmstudio_context_window(self):
        def handle(request):
            return httpx.Response(200, json={"loaded_context_length": 32768, "max_context_length": 131072})

        p = self.make_provider("lmstudio", "http://127.0.0.1:1234/v1", handle)
        self.assertEqual(await p.context_window("m"), 32768)

    async def test_openrouter_context_window(self):
        def handle(request):
            return httpx.Response(200, json={"data": [{"id": "openai/gpt-oss-120b", "context_length": 131072}]})

        p = self.make_provider("openrouter", "https://openrouter.ai/api/v1", handle)
        self.assertEqual(await p.context_window("openai/gpt-oss-120b"), 131072)

    async def test_openai_context_window_missing_is_none(self):
        def handle(request):
            return httpx.Response(200, json={"data": [{"id": "m"}]})

        p = self.make_provider("openai", "https://api.openai.com/v1", handle)
        self.assertIsNone(await p.context_window("m"))

    async def test_http_error_returns_none(self):
        def handle(request):
            return httpx.Response(500, text="boom")

        p = self.make_provider("llama_cpp", "http://127.0.0.1:8080/v1", handle)
        self.assertIsNone(await p.context_window("m"))

    async def test_result_is_cached(self):
        calls = []

        def handle(request):
            calls.append(1)
            return httpx.Response(200, json={"default_generation_settings": {"n_ctx": 4096}})

        p = self.make_provider("llama_cpp", "http://127.0.0.1:8080/v1", handle)
        await p.context_window("m")
        await p.context_window("m")
        self.assertEqual(len(calls), 1)

    async def test_none_result_is_also_cached(self):
        calls = []

        def handle(request):
            calls.append(1)
            return httpx.Response(500)

        p = self.make_provider("llama_cpp", "http://127.0.0.1:8080/v1", handle)
        await p.context_window("m")
        await p.context_window("m")
        self.assertEqual(len(calls), 1)

    async def test_empty_model_uses_default(self):
        paths = []

        def handle(request):
            paths.append(request.url.path)
            return httpx.Response(200, json={"loaded_context_length": 111, "max_context_length": 222})

        p = self.make_provider("lmstudio", "http://127.0.0.1:1234/v1", handle, default_model="qwen3:8b")
        self.assertEqual(await p.context_window(""), 111)
        self.assertTrue(paths[0].endswith("qwen3:8b"))


class ClaudeContextWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_window_recorded_from_model_usage(self):
        provider = cli_provider.ClaudeCodeProvider("test", "claude", "claude-sonnet-5")
        self.assertIsNone(await provider.context_window("claude-opus-5"))
        resp = ModelResponse(
            text="ok", tool_calls=[], finish_reason="stop",
            raw_provider_response={"session_id": "s", "modelUsage": {"claude-opus-5-5": {"inputTokens": 10, "contextWindow": 1000000}}},
        )
        with patch.object(provider, "_run_claude", new_callable=AsyncMock, return_value=resp):
            await provider._call("claude-opus-5", "system", "prompt", 10)
        self.assertEqual(await provider.context_window("claude-opus-5"), 1000000)

    async def test_missing_model_usage_leaves_window_none(self):
        provider = cli_provider.ClaudeCodeProvider("test", "claude", "claude-sonnet-5")
        resp = ModelResponse(text="ok", tool_calls=[], finish_reason="stop", raw_provider_response={"session_id": "s"})
        with patch.object(provider, "_run_claude", new_callable=AsyncMock, return_value=resp):
            await provider._call("claude-opus-5", "system", "prompt", 10)
        self.assertIsNone(await provider.context_window("claude-opus-5"))


class CodexContextWindowsTests(unittest.TestCase):
    def test_reads_and_scales_by_effective_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"models": [{"slug": "gpt-5.5", "context_window": 272000, "effective_context_window_percent": 95}, {"slug": "no-window"}]}
            Path(tmp, "models_cache.json").write_text(json.dumps(data))
            with patch.dict(os.environ, {"CODEX_HOME": tmp}):
                self.assertEqual(local_cli.codex_context_windows(), {"gpt-5.5": 258400})

    def test_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"CODEX_HOME": tmp}):
                self.assertEqual(local_cli.codex_context_windows(), {})


class CodexProviderContextWindowTests(unittest.IsolatedAsyncioTestCase):
    async def test_context_window_reads_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = {"models": [{"slug": "gpt-5.5", "context_window": 272000, "effective_context_window_percent": 95}, {"slug": "no-window"}]}
            Path(tmp, "models_cache.json").write_text(json.dumps(data))
            with patch.dict(os.environ, {"CODEX_HOME": tmp}):
                provider = cli_provider.CodexCliProvider("test", "codex", "gpt-5.5")
                self.assertEqual(await provider.context_window("gpt-5.5"), 258400)


if __name__ == "__main__":
    unittest.main()
