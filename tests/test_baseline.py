"""Tests for the baseline store."""

import json

import pytest
from click.testing import CliRunner

from promptdiff.baseline import check_compatible, load_baseline, save_baseline
from promptdiff.cli import main
from promptdiff.runner import RunResult


def _results(inputs):
    return [
        RunResult(
            input_text=text,
            output=f"answer to {text}",
            model="test-model",
            latency_ms=10.0,
            tokens_in=5,
            tokens_out=7,
        )
        for text in inputs
    ]


def test_round_trip(tmp_path):
    path = tmp_path / "baseline.json"
    inputs = ["hello", "world"]
    results = _results(inputs)

    save_baseline(path, "old prompt\n", "test-model", inputs, results)
    loaded = load_baseline(path)

    assert loaded.model == "test-model"
    assert [r.input_text for r in loaded.results] == inputs
    assert [r.output for r in loaded.results] == ["answer to hello", "answer to world"]
    assert loaded.results[0].tokens_out == 7


def test_check_compatible_clean(tmp_path):
    path = tmp_path / "baseline.json"
    inputs = ["hello"]
    save_baseline(path, "old prompt\n", "test-model", inputs, _results(inputs))
    loaded = load_baseline(path)

    assert check_compatible(loaded, "old prompt\n", "test-model", inputs) == []


def test_check_compatible_reports_each_drift(tmp_path):
    path = tmp_path / "baseline.json"
    inputs = ["hello"]
    save_baseline(path, "old prompt\n", "test-model", inputs, _results(inputs))
    loaded = load_baseline(path)

    assert any("prompt A text" in p for p in check_compatible(loaded, "changed prompt", "test-model", inputs))
    assert any("model differs" in p for p in check_compatible(loaded, "old prompt\n", "other-model", inputs))
    assert any("test case set" in p for p in check_compatible(loaded, "old prompt\n", "test-model", ["other"]))


def test_load_rejects_bad_schema_and_empty_cases(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"schema_version": 999}), encoding="utf-8")
    with pytest.raises(ValueError, match="schema version"):
        load_baseline(bad)

    empty = tmp_path / "empty.json"
    empty.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "prompt_fingerprint": "x",
                "model": "m",
                "cases_fingerprint": "y",
                "cases": [],
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="no cases"):
        load_baseline(empty)


async def _fake_run_both(_runner, _prompt_a, _prompt_b, inputs):
    return (_results(inputs), _results(inputs))


class _FakeRunner:
    def __init__(self, config):
        self.config = config

    async def run_batch(self, _prompt, inputs):
        return _results(inputs)


def test_compare_reuses_baseline_and_saves_it(tmp_path, monkeypatch):
    monkeypatch.setattr("promptdiff.cli._run_both", _fake_run_both)
    monkeypatch.setattr("promptdiff.cli.PromptRunner", _FakeRunner)
    prompt_a = tmp_path / "a.txt"
    prompt_b = tmp_path / "b.txt"
    cases = tmp_path / "cases.txt"
    baseline = tmp_path / "baseline.json"
    prompt_a.write_text("old prompt\n", encoding="utf-8")
    prompt_b.write_text("new prompt\n", encoding="utf-8")
    cases.write_text("hello\n", encoding="utf-8")

    first = CliRunner().invoke(
        main,
        [
            "compare",
            str(prompt_a),
            str(prompt_b),
            str(cases),
            "--no-semantic",
            "--save-baseline",
            str(baseline),
        ],
    )
    assert first.exit_code == 0, first.output
    assert baseline.exists()

    # prompt A is not re-run on the second compare: the fake _run_both would
    # blow up if it were called again
    async def _explode(*_args, **_kwargs):
        raise AssertionError("prompt A should not be re-run")

    monkeypatch.setattr("promptdiff.cli._run_both", _explode)
    second = CliRunner().invoke(
        main,
        [
            "compare",
            str(prompt_a),
            str(prompt_b),
            str(cases),
            "--no-semantic",
            "--baseline",
            str(baseline),
        ],
    )
    assert second.exit_code == 0, second.output
    assert "Reusing baseline" in second.output


def test_compare_rejects_mismatched_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr("promptdiff.cli._run_both", _fake_run_both)
    prompt_a = tmp_path / "a.txt"
    prompt_b = tmp_path / "b.txt"
    cases = tmp_path / "cases.txt"
    baseline = tmp_path / "baseline.json"
    prompt_a.write_text("old prompt\n", encoding="utf-8")
    prompt_b.write_text("new prompt\n", encoding="utf-8")
    cases.write_text("hello\n", encoding="utf-8")

    save_baseline(baseline, "different prompt\n", "test-model", ["hello"], _results(["hello"]))

    result = CliRunner().invoke(
        main,
        [
            "compare",
            str(prompt_a),
            str(prompt_b),
            str(cases),
            "--no-semantic",
            "--baseline",
            str(baseline),
        ],
    )
    assert result.exit_code == 1
    assert "does not match" in result.output
