"""Tests for the report module."""

from io import StringIO

from rich.console import Console

from promptdiff.diff import CaseDiff, ChangeType, DiffSummary
from promptdiff.report import DiffReport


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
