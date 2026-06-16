"""Tests for the report module."""

from io import StringIO

from rich.console import Console

from promptdiff.diff import CaseDiff, ChangeType, DiffSummary
from promptdiff.report import DiffReport, render_markdown


def _make_diff(change: ChangeType, sim: float = 0.9) -> CaseDiff:
    return CaseDiff(
        input_text="What is 2+2?",
        output_a="4",
        output_b="Four" if change != ChangeType.UNCHANGED else "4",
        change=change,
        similarity=sim,
        latency_delta_ms=10.0,
        token_delta=5,
    )


class TestDiffReport:
    def test_print_summary(self):
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        report = DiffReport(console)
        summary = DiffSummary(
            total=10, improved=2, regressed=3, unchanged=4, errors=1,
            avg_similarity=0.82, avg_latency_delta_ms=15.0, avg_token_delta=3.0,
        )
        report.print_summary(summary)
        output = buf.getvalue()
        assert "10 cases" in output

    def test_print_cases_hides_unchanged_by_default(self):
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        report = DiffReport(console)
        diffs = [
            _make_diff(ChangeType.UNCHANGED),
            _make_diff(ChangeType.REGRESSED, sim=0.5),
        ]
        report.print_cases(diffs, show_unchanged=False)
        output = buf.getvalue()
        # should only show the regressed one
        assert "50.0%" in output

    def test_all_unchanged_message(self):
        buf = StringIO()
        console = Console(file=buf, force_terminal=True, width=120)
        report = DiffReport(console)
        diffs = [_make_diff(ChangeType.UNCHANGED)]
        report.print_cases(diffs, show_unchanged=False)
        output = buf.getvalue()
        assert "unchanged" in output.lower()

    def test_severity_sort_keeps_worst_cases_first(self):
        report = DiffReport()
        diffs = [
            _make_diff(ChangeType.UNCHANGED, sim=1.0),
            _make_diff(ChangeType.REGRESSED, sim=0.8),
            _make_diff(ChangeType.ERROR, sim=0.0),
            _make_diff(ChangeType.REGRESSED, sim=0.2),
        ]

        ordered = report._ordered_cases(diffs, sort_by="severity")

        assert [i for i, _ in ordered] == [3, 4, 2, 1]


class TestRenderMarkdown:
    def _summary(self, **kwargs) -> DiffSummary:
        base = dict(
            total=2, improved=0, regressed=1, unchanged=1, errors=0,
            avg_similarity=0.6, avg_latency_delta_ms=10.0, avg_token_delta=5.0,
        )
        base.update(kwargs)
        return DiffSummary(**base)

    def test_summary_table_and_regression_section(self):
        diffs = [
            _make_diff(ChangeType.REGRESSED, sim=0.2),
            _make_diff(ChangeType.UNCHANGED, sim=1.0),
        ]
        md = render_markdown(diffs, self._summary())

        assert md.startswith("# PromptDiff Report")
        assert "| Total cases | 2 |" in md
        assert "## Top regressed cases" in md
        # the unchanged case is not listed in the regression table
        assert md.count("20.0%") == 1

    def test_custom_title(self):
        md = render_markdown([_make_diff(ChangeType.UNCHANGED)], self._summary(), title="v2 vs v1")
        assert md.startswith("# v2 vs v1")

    def test_gate_failures_rendered(self):
        gates = {"passed": False, "failures": ["regression rate 100.0% exceeds 0.0%"]}
        md = render_markdown([_make_diff(ChangeType.REGRESSED, sim=0.3)], self._summary(), gates=gates)

        assert "## Regression budget" in md
        assert "Status: failed" in md
        assert "regression rate 100.0% exceeds 0.0%" in md

    def test_no_gate_section_without_gates(self):
        md = render_markdown([_make_diff(ChangeType.UNCHANGED)], self._summary(regressed=0, unchanged=2))
        assert "Regression budget" not in md
        assert "No regressions." in md

    def test_input_pipes_and_newlines_are_escaped(self):
        diff = CaseDiff(
            input_text="line one\nwith | pipe",
            output_a="a", output_b="b",
            change=ChangeType.REGRESSED, similarity=0.1,
            latency_delta_ms=0.0, token_delta=0,
        )
        md = render_markdown([diff], self._summary(regressed=1, unchanged=0, total=1))

        assert "line one with \\| pipe" in md
        # the case row must stay on one physical line
        case_rows = [ln for ln in md.splitlines() if ln.startswith("| 1 |")]
        assert len(case_rows) == 1

    def test_top_n_limits_listed_cases(self):
        diffs = [
            _make_diff(ChangeType.REGRESSED, sim=0.81),
            _make_diff(ChangeType.ERROR, sim=0.0),
            _make_diff(ChangeType.REGRESSED, sim=0.22),
        ]
        summary = self._summary(total=3, improved=0, regressed=2, unchanged=0, errors=1)
        md = render_markdown(diffs, summary, top_n=2)

        # the two worst cases survive, the milder regression is dropped
        assert "0.0%" in md
        assert "22.0%" in md
        assert "81.0%" not in md
