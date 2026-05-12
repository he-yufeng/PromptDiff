"""Tests for the diff module."""

import json

from promptdiff.diff import ChangeType, PromptDiff
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
