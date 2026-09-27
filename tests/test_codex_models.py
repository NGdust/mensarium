import unittest
from unittest.mock import AsyncMock, Mock, patch

from mensarium.llm_providers import cli_provider, local_cli


class CodexCatalogTests(unittest.TestCase):
    def test_account_catalog_filters_config_and_hidden_models(self):
        pages = [
            {"data": [{"id": "internal", "model": "working"}, {"model": "hidden", "hidden": True}], "nextCursor": "next"},
            {"data": [{"model": "preferred", "isDefault": True}, {"model": "working"}]},
        ]
        with patch.object(local_cli, "codex_rpc", side_effect=pages) as rpc, patch.object(local_cli, "codex_config_model", return_value="gpt-5-codex"):
            self.assertEqual(local_cli.codex_models("codex"), ["preferred", "working"])
            self.assertEqual(rpc.call_args.args, ("codex", "model/list", {"cursor": "next"}))

    def test_supported_configured_model_has_priority(self):
        page = {"data": [{"model": "default", "isDefault": True}, {"model": "selected"}]}
        with patch.object(local_cli, "codex_rpc", return_value=page), patch.object(local_cli, "codex_config_model", return_value="selected"):
            self.assertEqual(local_cli.codex_models("codex"), ["selected", "default"])

    def test_discovery_failure_does_not_invent_models(self):
        with patch.object(local_cli, "codex_rpc", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(RuntimeError, "offline"):
                local_cli.codex_models("codex")

    def test_empty_catalog_is_rejected(self):
        with patch.object(local_cli, "codex_rpc", return_value={"data": []}):
            with self.assertRaisesRegex(RuntimeError, "no available models"):
                local_cli.codex_models("codex")

    def test_repeated_cursor_is_rejected(self):
        with patch.object(local_cli, "codex_rpc", return_value={"data": [{"model": "working"}], "nextCursor": "same"}):
            with self.assertRaisesRegex(RuntimeError, "repeated cursor"):
                local_cli.codex_models("codex")

    def test_detection_survives_catalog_failure(self):
        with patch.object(local_cli, "codex_models", side_effect=RuntimeError("offline")), patch.object(local_cli, "_run", return_value=(0, "logged in")):
            result = local_cli._codex("codex")
            self.assertEqual(result.models, [])
            self.assertEqual(result.default_model, "")

    def test_rpc_reads_combined_and_fragmented_responses(self):
        cases = [
            [b'{"id":1,"result":{}}\n{"id":2,"result":{"data":[]}}\n'],
            [b'{"id":1,"result":{}}\n{"id":2,', b'"result":{"data":[]}}\n'],
        ]
        for chunks in cases:
            with self.subTest(chunks=chunks):
                proc = Mock()
                proc.poll.return_value = None
                with patch.object(local_cli.subprocess, "Popen", return_value=proc), patch("select.select", return_value=([proc.stdout], [], [])), patch.object(local_cli.os, "read", side_effect=chunks):
                    self.assertEqual(local_cli.codex_rpc("codex", "model/list"), {"data": []})
                proc.kill.assert_called_once()
                proc.wait.assert_called_once()
                proc.stdin.close.assert_called_once()
                proc.stdout.close.assert_called_once()


class CodexProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsupported_model_never_executes(self):
        client = cli_provider.CodexCliProvider("test", "codex", "gpt-5-codex", max_retries=0)
        with patch.object(cli_provider, "codex_models", return_value=["working"]), patch.object(client, "_exec", new_callable=AsyncMock) as execute:
            with self.assertRaisesRegex(cli_provider.LLMError, "unavailable.*working"):
                await client._call("gpt-5-codex", "", "", 10)
            execute.assert_not_awaited()

    async def test_catalog_failure_becomes_provider_error(self):
        client = cli_provider.CodexCliProvider("test", "codex", "", max_retries=0)
        with patch.object(cli_provider, "codex_models", side_effect=RuntimeError("offline")):
            with self.assertRaisesRegex(cli_provider.LLMError, "cannot discover Codex models"):
                await client.list_models()
