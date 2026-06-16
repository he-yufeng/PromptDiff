from click.testing import CliRunner

from promptdiff.cli import main
from promptdiff.diff import PromptDiff, evaluate_gates
from promptdiff.runner import RunResult


class _DummyRunner:
    def __init__(self, config):
        self.config = config


async def _fake_error_run(_runner, _prompt_a, _prompt_b, inputs):
    return (
        [
            RunResult(
                input_text=inputs[0],
                output="",
                model="test-model",
                latency_ms=12.0,
                tokens_in=0,
                tokens_out=0,
                error="timeout",
            )
        ],
        [
            RunResult(
                input_text=inputs[0],
                output="ok",
                model="test-model",
                latency_ms=10.0,
                tokens_in=1,
                tokens_out=1,
            )
        ],
    )


async def _fake_regression_run(_runner, _prompt_a, _prompt_b, inputs):
    return (
        [
            RunResult(
                input_text=inputs[0],
                output="the expected answer",
                model="test-model",
                latency_ms=10.0,
                tokens_in=1,
                tokens_out=1,
            )
        ],
        [
            RunResult(
                input_text=inputs[0],
                output="completely different",
                model="test-model",
                latency_ms=40.0,
                tokens_in=1,
                tokens_out=5,
            )
        ],
    )


def _write_inputs(tmp_path):
    prompt_a = tmp_path / "a.txt"
    prompt_b = tmp_path / "b.txt"
    cases = tmp_path / "cases.txt"
    prompt_a.write_text("old prompt\n", encoding="utf-8")
    prompt_b.write_text("new prompt\n", encoding="utf-8")
    cases.write_text("hello\n", encoding="utf-8")
    return prompt_a, prompt_b, cases


def test_fail_on_error_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr("promptdiff.cli.PromptRunner", _DummyRunner)
    monkeypatch.setattr("promptdiff.cli._run_both", _fake_error_run)
    prompt_a, prompt_b, cases = _write_inputs(tmp_path)

    result = CliRunner().invoke(
        main,
        [
            "compare",
            str(prompt_a),
            str(prompt_b),
            str(cases),
            "--no-semantic",
            "--fail-on-error",
        ],
    )

    assert result.exit_code == 1


def test_errors_do_not_fail_without_ci_flag(tmp_path, monkeypatch):
    monkeypatch.setattr("promptdiff.cli.PromptRunner", _DummyRunner)
    monkeypatch.setattr("promptdiff.cli._run_both", _fake_error_run)
    prompt_a, prompt_b, cases = _write_inputs(tmp_path)

    result = CliRunner().invoke(
        main,
        [
            "compare",
            str(prompt_a),
            str(prompt_b),
            str(cases),
            "--no-semantic",
        ],
    )

    assert result.exit_code == 0, result.output


def test_compare_accepts_input_sort(tmp_path, monkeypatch):
    monkeypatch.setattr("promptdiff.cli.PromptRunner", _DummyRunner)
    monkeypatch.setattr("promptdiff.cli._run_both", _fake_error_run)
    prompt_a, prompt_b, cases = _write_inputs(tmp_path)

    result = CliRunner().invoke(
        main,
        [
            "compare",
            str(prompt_a),
            str(prompt_b),
            str(cases),
            "--no-semantic",
            "--sort",
            "input",
        ],
    )

    assert result.exit_code == 0, result.output


def test_validate_command_accepts_good_inputs(tmp_path):
    prompt_a, _prompt_b, cases = _write_inputs(tmp_path)

    result = CliRunner().invoke(main, ["validate", str(prompt_a), str(cases)])

    assert result.exit_code == 0, result.output
    assert "PromptDiff inputs look valid" in result.output
    assert "Test cases" in result.output


def test_validate_command_rejects_too_few_cases(tmp_path):
    prompt_a, _prompt_b, cases = _write_inputs(tmp_path)

    result = CliRunner().invoke(
        main,
        ["validate", str(prompt_a), str(cases), "--min-cases", "2"],
    )

    assert result.exit_code != 0
    assert "Only found 1 test case" in result.output


def _rr(inp, out, latency=10.0, tokens=1):
    return RunResult(input_text=inp, output=out, model="m", latency_ms=latency, tokens_in=1, tokens_out=tokens)


def _write_results(tmp_path, *, with_gate_failure=False):
    differ = PromptDiff(threshold=0.85, use_semantic=False)
    a = [_rr("q1", "the expected answer"), _rr("pipe | case", "same here")]
    b = [_rr("q1", "completely different", latency=40.0, tokens=6), _rr("pipe | case", "totally other text")]
    diffs, summary = differ.compare_batch(a, b)
    gates = evaluate_gates(summary, max_regression_rate=0.0 if with_gate_failure else None)
    path = tmp_path / "results.json"
    path.write_text(differ.to_json(diffs, summary, gates=gates), encoding="utf-8")
    return path


def test_report_renders_markdown_to_stdout(tmp_path):
    results = _write_results(tmp_path, with_gate_failure=True)

    result = CliRunner().invoke(main, ["report", str(results)])

    assert result.exit_code == 0, result.output
    assert "# PromptDiff Report" in result.output
    assert "## Top regressed cases" in result.output
    assert "Status: failed" in result.output
    # input containing a pipe is escaped so the table stays intact
    assert "pipe \\| case" in result.output


def test_report_writes_output_file(tmp_path):
    results = _write_results(tmp_path)
    out = tmp_path / "report.md"

    result = CliRunner().invoke(main, ["report", str(results), "--output", str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("# PromptDiff Report")


def test_report_rejects_invalid_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")

    result = CliRunner().invoke(main, ["report", str(bad)])

    assert result.exit_code != 0
    assert "invalid JSON" in result.output


def test_report_rejects_non_results_json(tmp_path):
    other = tmp_path / "other.json"
    other.write_text('{"hello": "world"}', encoding="utf-8")

    result = CliRunner().invoke(main, ["report", str(other)])

    assert result.exit_code != 0
    assert "not a PromptDiff results file" in result.output


def test_report_rejects_non_positive_top(tmp_path):
    results = _write_results(tmp_path)

    result = CliRunner().invoke(main, ["report", str(results), "--top", "0"])

    assert result.exit_code != 0
    assert "--top must be greater than zero" in result.output


def test_regression_budget_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr("promptdiff.cli.PromptRunner", _DummyRunner)
    monkeypatch.setattr("promptdiff.cli._run_both", _fake_regression_run)
    prompt_a, prompt_b, cases = _write_inputs(tmp_path)

    result = CliRunner().invoke(
        main,
        [
            "compare",
            str(prompt_a),
            str(prompt_b),
            str(cases),
            "--no-semantic",
            "--max-regression-rate",
            "0.5",
        ],
    )

    assert result.exit_code == 1
    assert "Regression budget failed" in result.output


def test_similarity_budget_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr("promptdiff.cli.PromptRunner", _DummyRunner)
    monkeypatch.setattr("promptdiff.cli._run_both", _fake_regression_run)
    prompt_a, prompt_b, cases = _write_inputs(tmp_path)

    result = CliRunner().invoke(
        main,
        [
            "compare",
            str(prompt_a),
            str(prompt_b),
            str(cases),
            "--no-semantic",
            "--min-avg-similarity",
            "0.9",
        ],
    )

    assert result.exit_code == 1
    assert "average similarity" in result.output


def test_error_rate_budget_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.setattr("promptdiff.cli.PromptRunner", _DummyRunner)
    monkeypatch.setattr("promptdiff.cli._run_both", _fake_error_run)
    prompt_a, prompt_b, cases = _write_inputs(tmp_path)

    result = CliRunner().invoke(
        main,
        [
            "compare",
            str(prompt_a),
            str(prompt_b),
            str(cases),
            "--no-semantic",
            "--max-error-rate",
            "0",
        ],
    )

    assert result.exit_code == 1
    assert "error rate" in result.output
