"""Tests for the runner module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from promptdiff.runner import PromptRunner, RunConfig, RunResult


class TestRunResult:
    def test_fields(self):
        r = RunResult(
            input_text="hello",
            output="world",
            model="gpt-4o-mini",
            latency_ms=150.0,
            tokens_in=10,
            tokens_out=20,
        )
        assert r.error is None
        assert r.output == "world"


class TestRunConfig:
    def test_defaults(self):
        c = RunConfig()
        assert c.model == "gpt-4o-mini"
        assert c.temperature == 0.0
        assert c.concurrency == 5

    def test_custom(self):
        c = RunConfig(model="claude-sonnet-4-6", temperature=0.5, concurrency=10)
        assert c.model == "claude-sonnet-4-6"


class TestPromptRunner:
    @pytest.mark.asyncio
    async def test_run_single_success(self):
        runner = PromptRunner(RunConfig(api_key="test-key"))

        # mock the client
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "42"
        mock_resp.model = "gpt-4o-mini"
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 5

        runner._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        result = await runner.run_single("Be helpful.", "What is 6*7?")
        assert result.output == "42"
        assert result.error is None
        assert result.tokens_in == 10

    @pytest.mark.asyncio
    async def test_run_single_error(self):
        runner = PromptRunner(RunConfig(api_key="test-key"))
        runner._client.chat.completions.create = AsyncMock(side_effect=Exception("rate limit"))

        result = await runner.run_single("Be helpful.", "test")
        assert result.error == "rate limit"
        assert result.output == ""

    @pytest.mark.asyncio
    async def test_run_batch(self):
        runner = PromptRunner(RunConfig(api_key="test-key"))

        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = "answer"
        mock_resp.model = "gpt-4o-mini"
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 10
        mock_resp.usage.completion_tokens = 5

        runner._client.chat.completions.create = AsyncMock(return_value=mock_resp)

        results = await runner.run_batch("system prompt", ["q1", "q2", "q3"])
        assert len(results) == 3
        assert all(r.output == "answer" for r in results)
