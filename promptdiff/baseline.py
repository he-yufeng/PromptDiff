"""Baseline store for prompt A outputs.

Re-running the baseline prompt on every compare costs as many API calls as
the candidate and adds run-to-run noise to the diff. A saved baseline pins
prompt A's outputs once and lets later compares re-use them, as long as the
prompt text, model, and test-case set are unchanged — any drift fails fast
instead of silently diffing against stale outputs.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

from .runner import RunResult

SCHEMA_VERSION = 1


def _prompt_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _cases_fingerprint(inputs: list[str]) -> str:
    digest = hashlib.sha256()
    for item in inputs:
        digest.update(item.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()[:16]


@dataclass
class Baseline:
    """A saved set of prompt A outputs with the fingerprints they belong to."""

    prompt_fingerprint: str
    model: str
    cases_fingerprint: str
    created_at: float
    results: list[RunResult]


def save_baseline(
    path: str | Path,
    prompt_text: str,
    model: str,
    inputs: list[str],
    results: list[RunResult],
) -> None:
    """Write prompt A's outputs and their fingerprints to ``path`` as JSON."""
    payload = {
        "schema_version": SCHEMA_VERSION,
        "prompt_fingerprint": _prompt_fingerprint(prompt_text),
        "model": model,
        "cases_fingerprint": _cases_fingerprint(list(inputs)),
        "created_at": time.time(),
        "cases": [
            {
                "input": r.input_text,
                "output": r.output,
                "latency_ms": r.latency_ms,
                "tokens_in": r.tokens_in,
                "tokens_out": r.tokens_out,
                "error": r.error,
            }
            for r in results
        ],
    }
    Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def load_baseline(path: str | Path) -> Baseline:
    """Load a baseline, rejecting unknown schema versions and empty files."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"unsupported baseline schema version: {payload.get('schema_version')!r}")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError(f"{path}: baseline has no cases")
    results = [
        RunResult(
            input_text=str(case["input"]),
            output=str(case["output"]),
            model=str(payload["model"]),
            latency_ms=float(case.get("latency_ms", 0)),
            tokens_in=int(case.get("tokens_in", 0)),
            tokens_out=int(case.get("tokens_out", 0)),
            error=case.get("error"),
        )
        for case in cases
    ]
    return Baseline(
        prompt_fingerprint=str(payload["prompt_fingerprint"]),
        model=str(payload["model"]),
        cases_fingerprint=str(payload["cases_fingerprint"]),
        created_at=float(payload.get("created_at", 0)),
        results=results,
    )


def check_compatible(baseline: Baseline, prompt_text: str, model: str, inputs: list[str]) -> list[str]:
    """Mismatch descriptions between a baseline and the current run.

    An empty list means the baseline may be reused; anything else must be
    shown to the user and treated as fatal, since diffing against stale
    outputs would produce a confident-looking wrong answer.
    """
    problems: list[str] = []
    if baseline.prompt_fingerprint != _prompt_fingerprint(prompt_text):
        problems.append("prompt A text changed since the baseline was saved")
    if baseline.model != model:
        problems.append(f"model differs (baseline used {baseline.model!r}, this run uses {model!r})")
    if baseline.cases_fingerprint != _cases_fingerprint(list(inputs)):
        problems.append("test case set changed since the baseline was saved")
    return problems
