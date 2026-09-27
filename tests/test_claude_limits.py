import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx

from mensarium.llm_providers import cli_provider


class ClaudeLimitsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.credentials = Path(self.tmp.name) / '.credentials.json'
        self.credentials.write_text(json.dumps({'claudeAiOauth': {'accessToken': 'test-token'}}))
        env = patch.dict(cli_provider.os.environ, {'CLAUDE_CONFIG_DIR': self.tmp.name})
        env.start()
        self.addCleanup(env.stop)
        self.provider = cli_provider.ClaudeCodeProvider('test', 'claude', 'unused', max_retries=0)
        model = patch.object(self.provider, '_call', new_callable=AsyncMock, side_effect=AssertionError('Model must not be called'))
        self.model = model.start()
        self.addCleanup(model.stop)

    async def fetch(self, response=None, error=None):
        with patch.object(cli_provider.httpx, 'AsyncClient') as factory:
            client = factory.return_value.__aenter__.return_value
            client.get = AsyncMock(return_value=response, side_effect=error)
            try:
                return await self.provider.fetch_limits()
            finally:
                self.model.assert_not_awaited()

    async def test_exhausted_quota_is_returned_without_generation(self):
        reset = '2026-10-01T12:00:00+00:00'
        response = httpx.Response(200, json={
            'five_hour': {'utilization': 12.5, 'resets_at': reset},
            'seven_day': {'utilization': 100, 'resets_at': reset},
            'seven_day_sonnet': None,
            'extra_usage': {'utilization': 45},
        })
        windows = await self.fetch(response)
        self.assertEqual([(w.label, w.used_percent, w.resets_at) for w in windows],
                         [('5 hours', 12.5, reset), ('7 days', 100, reset)])
        self.assertEqual(self.provider.limits_source, 'claude OAuth usage')
        self.assertIsNotNone(self.provider.limits_at)

    async def test_http_errors_do_not_expose_response_or_token(self):
        for status in (401, 403, 429, 500):
            with self.subTest(status=status):
                with self.assertRaises(cli_provider.LLMError) as caught:
                    await self.fetch(httpx.Response(status, text='secret-response test-token'))
                self.assertNotIn('test-token', str(caught.exception))
                self.assertNotIn('secret-response', str(caught.exception))

    async def test_network_error_is_safe(self):
        with self.assertRaisesRegex(cli_provider.LLMError, 'network error or timeout') as caught:
            await self.fetch(error=httpx.ConnectError('test-token'))
        self.assertNotIn('test-token', str(caught.exception))

    async def test_invalid_response_preserves_previous_snapshot(self):
        await self.fetch(httpx.Response(200, json={'seven_day': {'utilization': 100}}))
        previous = self.provider.limits
        checked_at = self.provider.limits_at
        for data in ([], {}, {'five_hour': {'utilization': True}},
                     {'five_hour': {'utilization': -1}},
                     {'five_hour': {'utilization': '100'}},
                     {'five_hour': {'utilization': 10, 'resets_at': 123}}):
            with self.subTest(data=data):
                with self.assertRaisesRegex(cli_provider.LLMError, 'invalid or empty'):
                    await self.fetch(httpx.Response(200, json=data))
                self.assertIs(self.provider.limits, previous)
                self.assertEqual(self.provider.limits_at, checked_at)

    async def test_missing_credentials_do_not_send_request(self):
        self.credentials.unlink()
        with patch.object(cli_provider.httpx, 'AsyncClient') as factory:
            with self.assertRaisesRegex(cli_provider.LLMError, 'credentials'):
                await self.provider.fetch_limits()
            factory.assert_not_called()
        self.model.assert_not_awaited()

    async def test_invalid_credentials_do_not_send_request(self):
        for data in ('invalid json', '[]', '{}', '{"claudeAiOauth": {"accessToken": ""}}'):
            with self.subTest(data=data):
                self.credentials.write_text(data)
                with patch.object(cli_provider.httpx, 'AsyncClient') as factory:
                    with self.assertRaises(cli_provider.LLMError):
                        await self.provider.fetch_limits()
                    factory.assert_not_called()
        self.model.assert_not_awaited()
