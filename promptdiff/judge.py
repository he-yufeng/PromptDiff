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
        # try to parse JSON from the response
        data = json.loads(raw)
        verdict = data.get("verdict", "equivalent")
        reason = data.get("reason", "")

        if verdict == "better":
            case.change = ChangeType.IMPROVED
        elif verdict == "worse":
            case.change = ChangeType.REGRESSED
        else:
            case.change = ChangeType.UNCHANGED

        case.judge_verdict = verdict
        case.judge_reason = reason

    except Exception:
        # if judge fails, keep the original classification
        pass

    return case
