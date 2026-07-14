"""Tests for the diff module."""

import json

import pytest

from promptdiff.diff import (
    ChangeType,
    DiffSummary,
    PromptDiff,
    Severity,
    classify_severity,
    diffs_from_payload,
    evaluate_gates,
    severity_breakdown,
)
from promptdiff.runner import RunResult


def _make_result(inp: str, output: str, latency: float = 100.0, tokens: int = 50, error=None) -> RunResult:
    return RunResult(
        input_text=inp,
        output=output,
        model="test-model",
        latency_ms=latency,
        tokens_in=20,
        tokens_out=tokens,
        error=error,
    )


class TestPromptDiff:
    def test_identical_outputs_are_unchanged(self):
        differ = PromptDiff(threshold=0.85, use_semantic=False)
        a = _make_result("hello", "The answer is 42.")
        b = _make_result("hello", "The answer is 42.")
        case = differ.compare_pair(a, b)
        assert case.change == ChangeType.UNCHANGED
        assert case.similarity == 1.0

    def test_different_outputs_are_regressed(self):
        differ = PromptDiff(threshold=0.85, use_semantic=False)
        a = _make_result("hello", "The capital of France is Paris.")
        b = _make_result("hello", "I like bananas and trains.")
        case = differ.compare_pair(a, b)
        assert case.change == ChangeType.REGRESSED
        assert case.similarity < 0.85

    def test_compare_batch_rejects_mismatched_lengths(self):
        # A length mismatch must fail loudly, not silently drop cases via zip()
        # (an assert would be stripped under `python -O`).
        differ = PromptDiff(use_semantic=False)
        a = [_make_result("q1", "a1"), _make_result("q2", "a2")]
        b = [_make_result("q1", "a1")]
        with pytest.raises(ValueError, match="equal length"):
            differ.compare_batch(a, b)

    def test_error_case(self):
        differ = PromptDiff(use_semantic=False)
        a = _make_result("hello", "", error="timeout")
        b = _make_result("hello", "fine")
        case = differ.compare_pair(a, b)
        assert case.change == ChangeType.ERROR
        assert case.error_a == "timeout"
        assert case.error_b is None

    def test_latency_delta(self):
        differ = PromptDiff(use_semantic=False)
        a = _make_result("hello", "same output", latency=100.0)
        b = _make_result("hello", "same output", latency=200.0)
        case = differ.compare_pair(a, b)
        assert case.latency_delta_ms == 100.0

    def test_token_delta(self):
        differ = PromptDiff(use_semantic=False)
        a = _make_result("hello", "short", tokens=10)
        b = _make_result("hello", "short", tokens=30)
        case = differ.compare_pair(a, b)
        assert case.token_delta == 20

    def test_batch_summary(self):
        differ = PromptDiff(threshold=0.85, use_semantic=False)
        results_a = [
            _make_result("q1", "The answer is 42."),
            _make_result("q2", "Paris is the capital."),
            _make_result("q3", "Python is great."),
        ]
        results_b = [
            _make_result("q1", "The answer is 42."),  # unchanged
            _make_result("q2", "I enjoy eating pizza."),  # regressed (different)
            _make_result("q3", "Python is great."),  # unchanged
        ]
        diffs, summary = differ.compare_batch(results_a, results_b)
        assert summary.total == 3
        assert summary.unchanged == 2
        assert summary.regressed == 1

    def test_lexical_similarity_edge_cases(self):
        assert PromptDiff._lexical_similarity("", "") == 1.0
        assert PromptDiff._lexical_similarity("hello", "") == 0.0
        assert PromptDiff._lexical_similarity("", "hello") == 0.0
        assert PromptDiff._lexical_similarity("hello world", "hello world") == 1.0

    def test_both_empty_outputs_are_unchanged(self):
        # Two empty (or whitespace-only) outputs are identical, not a regression.
        # The semantic path must agree with the lexical fallback's "", "" -> 1.0.
        assert PromptDiff(use_semantic=False)._semantic_similarity("", "") == 1.0
        assert PromptDiff(use_semantic=True)._semantic_similarity("  ", "\n") == 1.0

        differ = PromptDiff(threshold=0.85, use_semantic=False)
        case = differ.compare_pair(_make_result("q", ""), _make_result("q", ""))
        assert case.change == ChangeType.UNCHANGED
        assert case.similarity == 1.0

    def test_to_json(self):
        differ = PromptDiff(use_semantic=False)
        a = [_make_result("q1", "answer A")]
        b = [_make_result("q1", "answer A")]
        diffs, summary = differ.compare_batch(a, b)
        raw = differ.to_json(diffs, summary)
        data = json.loads(raw)
        assert data["summary"]["total"] == 1
        assert len(data["cases"]) == 1
        assert "judge_verdict" in data["cases"][0]
        assert "error_a" in data["cases"][0]

    def test_error_details_are_serialized(self):
        differ = PromptDiff(use_semantic=False)
        a = [_make_result("q1", "", error="timeout")]
        b = [_make_result("q1", "answer")]
        diffs, summary = differ.compare_batch(a, b)
        data = json.loads(differ.to_json(diffs, summary))
        assert data["summary"]["errors"] == 1
        assert data["cases"][0]["error_a"] == "timeout"
        assert data["cases"][0]["error_b"] is None

    def test_threshold_boundary(self):
        """With high threshold, even similar outputs count as changed."""
        differ = PromptDiff(threshold=0.99, use_semantic=False)
        a = _make_result("q", "the cat sat on the mat")
        b = _make_result("q", "the cat sat on the rug")
        case = differ.compare_pair(a, b)
        # these share most words but not all, so similarity < 0.99
        assert case.change == ChangeType.REGRESSED


class TestSeverity:
    def test_unchanged_and_improved_have_no_severity(self):
        assert classify_severity(ChangeType.UNCHANGED, 1.0, 0.85) is Severity.NONE
        assert classify_severity(ChangeType.IMPROVED, 0.4, 0.85) is Severity.NONE

    def test_errors_are_always_major(self):
        assert classify_severity(ChangeType.ERROR, 0.0, 0.85) is Severity.MAJOR

    def test_regression_bands_track_threshold(self):
        # threshold 0.6: minor down to 0.4, moderate down to 0.2, major below
        assert classify_severity(ChangeType.REGRESSED, 0.55, 0.6) is Severity.MINOR
        assert classify_severity(ChangeType.REGRESSED, 0.30, 0.6) is Severity.MODERATE
        assert classify_severity(ChangeType.REGRESSED, 0.05, 0.6) is Severity.MAJOR

    def test_near_threshold_regression_is_minor(self):
        assert classify_severity(ChangeType.REGRESSED, 0.84, 0.85) is Severity.MINOR

    def test_zero_threshold_falls_back_to_major(self):
        assert classify_severity(ChangeType.REGRESSED, 0.0, 0.0) is Severity.MAJOR

    def test_breakdown_counts_only_risky_cases(self):
        differ = PromptDiff(threshold=0.85, use_semantic=False)
        a = [
            _make_result("q1", "the quick brown fox"),
            _make_result("q2", "stable answer"),
            _make_result("q3", "first reply", error="boom"),
        ]
        b = [
            _make_result("q1", "a totally unrelated sentence here"),  # major regression
            _make_result("q2", "stable answer"),  # unchanged
            _make_result("q3", "second reply"),  # error
        ]
        diffs, _ = differ.compare_batch(a, b)
        counts = severity_breakdown(diffs, 0.85)
        assert counts["major"] == 2  # the regression and the error
        assert sum(counts.values()) == 2


def test_to_json_records_threshold():
    differ = PromptDiff(threshold=0.7, use_semantic=False)
    a = [_make_result("q1", "answer A")]
    b = [_make_result("q1", "answer A")]
    diffs, summary = differ.compare_batch(a, b)
    data = json.loads(differ.to_json(diffs, summary))
    assert data["threshold"] == 0.7


def test_diffs_from_payload_round_trip():
    differ = PromptDiff(threshold=0.85, use_semantic=False)
    a = [
        _make_result("q1", "the expected answer"),
        _make_result("q2", "alpha", error="boom"),
    ]
    b = [
        _make_result("q1", "completely different text", latency=200.0, tokens=80),
        _make_result("q2", "beta"),
    ]
    diffs, summary = differ.compare_batch(a, b)

    payload = json.loads(differ.to_json(diffs, summary, gates={"passed": True}))
    restored_diffs, restored_summary = diffs_from_payload(payload)

    assert restored_summary == summary
    assert restored_diffs == diffs


def test_diffs_from_payload_rejects_unknown_change():
    payload = {
        "summary": {
            "total": 1, "improved": 0, "regressed": 0, "unchanged": 1, "errors": 0,
            "avg_similarity": 1.0, "avg_latency_delta_ms": 0.0, "avg_token_delta": 0.0,
        },
        "cases": [{
            "input": "q", "output_a": "x", "output_b": "x", "change": "bogus",
            "similarity": 1.0, "latency_delta_ms": 0.0, "token_delta": 0,
        }],
    }
    try:
        diffs_from_payload(payload)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for unknown change type")


def test_evaluate_gates_reports_budget_failures():
    summary = DiffSummary(
        total=10,
        improved=0,
        regressed=2,
        unchanged=8,
        errors=0,
        avg_similarity=0.9,
        avg_latency_delta_ms=120.0,
        avg_token_delta=8.0,
    )

    gates = evaluate_gates(
        summary,
        max_regression_rate=0.1,
        max_avg_latency_increase_ms=100,
        max_avg_token_increase=10,
    )

    assert gates["passed"] is False
    assert len(gates["failures"]) == 2


def test_evaluate_gates_checks_similarity_and_error_rate():
    summary = DiffSummary(
        total=10,
        improved=0,
        regressed=1,
        unchanged=7,
        errors=2,
        avg_similarity=0.79,
        avg_latency_delta_ms=0.0,
        avg_token_delta=0.0,
    )

    gates = evaluate_gates(summary, min_avg_similarity=0.8, max_error_rate=0.1)

    assert gates["passed"] is False
    assert gates["error_rate"] == 0.2
    assert gates["avg_similarity"] == 0.79
    assert gates["limits"]["min_avg_similarity"] == 0.8
    assert len(gates["failures"]) == 2


def test_threshold_must_be_within_unit_interval():
    import pytest

    for bad in (1.5, 85, -0.1):
        with pytest.raises(ValueError, match="between 0 and 1"):
            PromptDiff(threshold=bad)
    # the [0, 1] endpoints are valid
    PromptDiff(threshold=0.0)
    PromptDiff(threshold=1.0)
