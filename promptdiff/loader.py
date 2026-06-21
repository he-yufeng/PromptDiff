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
        # Don't strip leading blank lines: that would shift every line number,
        # so a parse error would point at the wrong physical line. Keep the file
        # as-is and skip blank lines inside the loop instead.
        lines = p.read_text(encoding="utf-8").splitlines()
        cases = []
        for line_no, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{p}:{line_no}: invalid JSONL: {exc.msg}") from exc
            cases.append(_extract_input(item, where=f"{p}:{line_no}"))
        return cases

    if suffix == ".json":
        data = json.loads(p.read_text(encoding="utf-8"))
        return _extract_inputs(data, where=str(p))

    if suffix in (".yaml", ".yml"):
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
        return _extract_inputs(data, where=str(p))

    # plain text fallback
    return [line.strip() for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def _extract_inputs(data, where: str) -> list[str]:
    """Extract input strings from a list of strings or dicts."""
    if not isinstance(data, list):
        raise ValueError(f"{where}: expected a list of strings or objects with an input field")
    result = []
    for index, item in enumerate(data, start=1):
        result.append(_extract_input(item, where=f"{where}[{index}]"))
    return result


def _extract_input(item, where: str) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, dict) and "input" in item:
        value = item["input"]
        if isinstance(value, str):
            return value
        raise ValueError(f"{where}: input must be a string, got {type(value).__name__}")
    raise ValueError(f"{where}: expected a string or an object with an input field")
