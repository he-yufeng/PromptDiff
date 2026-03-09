"""Run prompts through LLM APIs and collect responses."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any

from openai import AsyncOpenAI


@dataclass
class RunResult:
    """Single prompt execution result."""

    input_text: str
    output: str
    model: str
    latency_ms: float
    tokens_in: int
    tokens_out: int
    error: str | None = None


@dataclass
class RunConfig:
    """Configuration for a prompt run."""

    model: str = "gpt-4o-mini"
    temperature: float = 0.0
    max_tokens: int = 1024
    base_url: str | None = None
    api_key: str | None = None
    concurrency: int = 5


class PromptRunner:
    """Runs a prompt template against a list of test inputs via any OpenAI-compatible API."""

    def __init__(self, config: RunConfig | None = None):
        self.config = config or RunConfig()
        kwargs: dict[str, Any] = {}
        if self.config.base_url:
            kwargs["base_url"] = self.config.base_url
        if self.config.api_key:
            kwargs["api_key"] = self.config.api_key
        self._client = AsyncOpenAI(**kwargs)

    async def run_single(self, system_prompt: str, user_input: str) -> RunResult:
        """Run one prompt + input through the model."""
        t0 = time.perf_counter()
        try:
            resp = await self._client.chat.completions.create(
                model=self.config.model,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_input},
                ],
            )
            elapsed = (time.perf_counter() - t0) * 1000
            choice = resp.choices[0]
            usage = resp.usage
            return RunResult(
                input_text=user_input,
                output=choice.message.content or "",
                model=resp.model,
                latency_ms=round(elapsed, 1),
                tokens_in=usage.prompt_tokens if usage else 0,
                tokens_out=usage.completion_tokens if usage else 0,
            )
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            return RunResult(
                input_text=user_input,
                output="",
                model=self.config.model,
                latency_ms=round(elapsed, 1),
                tokens_in=0,
                tokens_out=0,
                error=str(e),
            )

    async def run_batch(self, system_prompt: str, inputs: list[str]) -> list[RunResult]:
        """Run a prompt against all inputs with bounded concurrency."""
        sem = asyncio.Semaphore(self.config.concurrency)

        async def _run(inp: str) -> RunResult:
            async with sem:
                return await self.run_single(system_prompt, inp)

        return await asyncio.gather(*[_run(inp) for inp in inputs])
