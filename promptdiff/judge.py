"""LLM-as-judge for determining if prompt B is better or worse than A."""

from __future__ import annotations

import json

from openai import AsyncOpenAI

from promptdiff.diff import CaseDiff, ChangeType

JUDGE_SYSTEM_PROMPT = """\
You are an impartial judge comparing two LLM outputs for the same input.
Output A is from the original prompt, Output B is from the updated prompt.

Evaluate whether Output B is better, worse, or equivalent to Output A.
Consider: accuracy, helpfulness, clarity, and completeness.

Respond with ONLY valid JSON:
{"verdict": "better" | "worse" | "equivalent", "reason": "<brief explanation>"}
"""

JUDGE_USER_TEMPLATE = """\
Input: {input}

Output A (original):
{output_a}

Output B (updated):
{output_b}
"""


async def judge_case(
    case: CaseDiff,
    client: AsyncOpenAI,
    model: str = "gpt-4o-mini",
) -> CaseDiff:
    """Use an LLM judge to classify a changed case as improved or regressed."""
    if case.change == ChangeType.UNCHANGED or case.change == ChangeType.ERROR:
        return case

    try:
        resp = await client.chat.completions.create(
            model=model,
            temperature=0.0,
            max_tokens=256,
            messages=[
                {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": JUDGE_USER_TEMPLATE.format(
                        input=case.input_text[:500],
                        output_a=case.output_a[:1000],
                        output_b=case.output_b[:1000],
                    ),
                },
            ],
        )
        raw = resp.choices[0].message.content or ""
    except Exception:
        # LLM call failed (network, auth, ...) — keep the original classification
        return case

    parsed = _parse_verdict(raw)
    if parsed is None:
        # judge reply wasn't parseable — keep the original classification rather
        # than guessing "equivalent" and masking a real change
        return case

    verdict, reason = parsed
    case.change = _verdict_to_change(verdict)
    case.judge_verdict = verdict
    case.judge_reason = reason
    return case


def _parse_verdict(raw: str) -> tuple[str, str] | None:
    """Pull the ``{verdict, reason}`` object out of a judge reply.

    Models routinely wrap JSON in ```json fences or surround it with prose
    despite being told to return JSON only; a bare ``json.loads`` then fails
    and the judge silently does nothing. This strips fences and falls back to
    the first ``{...}`` block. Returns ``None`` when no valid verdict is found
    so the caller can keep the original classification.
    """
    text = (raw or "").strip()
    if text.startswith("```"):
        newline = text.find("\n")
        last_fence = text.rfind("```")
        if newline != -1 and last_fence > newline:
            text = text[newline + 1 : last_fence].strip()

    data = _loads_object(text)
    if data is None:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            data = _loads_object(text[start : end + 1])

    if not isinstance(data, dict):
        return None
    verdict = data.get("verdict")
    if verdict not in {"better", "worse", "equivalent"}:
        return None
    reason = data.get("reason", "")
    return verdict, reason if isinstance(reason, str) else str(reason)


def _loads_object(text: str) -> dict | list | None:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None


def _verdict_to_change(verdict: str) -> ChangeType:
    if verdict == "better":
        return ChangeType.IMPROVED
    if verdict == "worse":
        return ChangeType.REGRESSED
    return ChangeType.UNCHANGED
