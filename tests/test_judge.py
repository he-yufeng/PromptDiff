"""Tests for judge reply parsing (the deterministic core of judge.py)."""

from __future__ import annotations

from promptdiff.diff import ChangeType
from promptdiff.judge import _parse_verdict, _verdict_to_change


def test_parses_plain_json():
    assert _parse_verdict('{"verdict": "better", "reason": "clearer"}') == (
        "better",
        "clearer",
    )


def test_parses_markdown_fenced_json():
    raw = '```json\n{"verdict": "worse", "reason": "lost detail"}\n```'
    assert _parse_verdict(raw) == ("worse", "lost detail")


def test_parses_json_surrounded_by_prose():
    raw = 'Sure! Here is my verdict:\n{"verdict": "equivalent", "reason": "same"}\nHope that helps.'
    assert _parse_verdict(raw) == ("equivalent", "same")


def test_unparseable_returns_none():
    assert _parse_verdict("I think B is a bit better, honestly.") is None
    assert _parse_verdict("") is None
    assert _parse_verdict("```\nnot json at all\n```") is None


def test_invalid_verdict_value_returns_none():
    # a JSON object without a recognised verdict shouldn't classify anything
    assert _parse_verdict('{"verdict": "maybe", "reason": "x"}') is None
    assert _parse_verdict('{"reason": "no verdict key"}') is None


def test_missing_reason_defaults_empty():
    assert _parse_verdict('{"verdict": "better"}') == ("better", "")


def test_verdict_to_change_mapping():
    assert _verdict_to_change("better") == ChangeType.IMPROVED
    assert _verdict_to_change("worse") == ChangeType.REGRESSED
    assert _verdict_to_change("equivalent") == ChangeType.UNCHANGED
