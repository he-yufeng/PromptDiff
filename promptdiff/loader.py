"""Load prompts and test cases from files."""

from __future__ import annotations

import json
from pathlib import Path

import yaml


def load_prompt(path: str) -> str:
    """Load a prompt from a text file."""
    return Path(path).read_text(encoding="utf-8").strip()


def load_test_cases(path: str) -> list[str]:
    """Load test inputs from a file.

    Supported formats:
    - .jsonl: one JSON object per line with an "input" field
    - .json: array of strings or array of objects with "input" field
    - .yaml/.yml: list of strings or list of objects with "input" field
    - .txt: one test case per line
    """
    p = Path(path)
    suffix = p.suffix.lower()

    if suffix == ".jsonl":
        lines = p.read_text(encoding="utf-8").strip().splitlines()
        return [json.loads(line)["input"] for line in lines if line.strip()]

    if suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        return _extract_inputs(data)

    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        return _extract_inputs(data)

    # plain text fallback
    return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _extract_inputs(data: list) -> list[str]:
    """Extract input strings from a list of strings or dicts."""
    result = []
    for item in data:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, dict) and "input" in item:
            result.append(item["input"])
        else:
            raise ValueError(f"Can't extract input from: {item!r}")
    return result
