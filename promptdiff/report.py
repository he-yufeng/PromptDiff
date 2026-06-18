"""Rich terminal report for prompt diffs."""

from __future__ import annotations

import html
import xml.etree.ElementTree as ET

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from promptdiff.diff import (
    CaseDiff,
    ChangeType,
    DiffSummary,
    Severity,
    classify_severity,
    severity_breakdown,
)

_CHANGE_COLORS = {
    ChangeType.IMPROVED: "green",
    ChangeType.REGRESSED: "red",
    ChangeType.UNCHANGED: "dim",
    ChangeType.ERROR: "yellow",
}

_CHANGE_ICONS = {
    ChangeType.IMPROVED: "+",
    ChangeType.REGRESSED: "-",
    ChangeType.UNCHANGED: "=",
    ChangeType.ERROR: "!",
}

_SEVERITY_COLORS = {
    Severity.MAJOR: "red",
    Severity.MODERATE: "yellow",
    Severity.MINOR: "dim",
    Severity.NONE: "dim",
}

# default cutoff, kept in sync with the compare command's --threshold
DEFAULT_THRESHOLD = 0.85


def _severity_phrase(counts: dict[str, int]) -> str:
    """Render a severity breakdown like '1 major, 2 moderate'."""
    parts = [
        f"{counts[sev.value]} {sev.value}"
        for sev in (Severity.MAJOR, Severity.MODERATE, Severity.MINOR)
        if counts.get(sev.value)
    ]
    return ", ".join(parts)


class DiffReport:
    """Pretty-print prompt diff results to the terminal."""

    def __init__(self, console: Console | None = None):
        self.console = console or Console()

    def print_summary(self, summary: DiffSummary) -> None:
        parts = []
        if summary.unchanged:
            parts.append(f"[dim]{summary.unchanged} unchanged[/dim]")
        if summary.regressed:
            parts.append(f"[red]{summary.regressed} regressed[/red]")
        if summary.improved:
            parts.append(f"[green]{summary.improved} improved[/green]")
        if summary.errors:
            parts.append(f"[yellow]{summary.errors} errors[/yellow]")

        header = f"[bold]{summary.total} cases[/bold]: " + ", ".join(parts)

        stats = (
            f"avg similarity: {summary.avg_similarity:.2%}  |  "
            f"avg latency delta: {summary.avg_latency_delta_ms:+.0f}ms  |  "
            f"avg token delta: {summary.avg_token_delta:+.0f}"
        )

        self.console.print(Panel(f"{header}\n{stats}", title="PromptDiff Summary", border_style="blue"))

    @staticmethod
    def _ordered_cases(
        diffs: list[CaseDiff],
        sort_by: str,
    ) -> list[tuple[int, CaseDiff]]:
        indexed = list(enumerate(diffs, 1))
        if sort_by == "input":
            return indexed

        rank = {
            ChangeType.ERROR: 0,
            ChangeType.REGRESSED: 1,
            ChangeType.IMPROVED: 2,
            ChangeType.UNCHANGED: 3,
        }
        return sorted(
            indexed,
            key=lambda item: (
                rank[item[1].change],
                item[1].similarity,
                -abs(item[1].token_delta),
                -abs(item[1].latency_delta_ms),
            ),
        )

    def print_cases(
        self,
        diffs: list[CaseDiff],
        show_unchanged: bool = False,
        sort_by: str = "severity",
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        table = Table(show_header=True, header_style="bold", expand=True)
        table.add_column("#", width=3, justify="right")
        table.add_column("", width=1)  # icon
        table.add_column("Input", ratio=2)
        table.add_column("Severity", width=9)
        table.add_column("Similarity", width=10, justify="right")
        table.add_column("Latency", width=9, justify="right")
        table.add_column("Tokens", width=8, justify="right")

        for i, d in self._ordered_cases(diffs, sort_by):
            if d.change == ChangeType.UNCHANGED and not show_unchanged:
                continue

            color = _CHANGE_COLORS[d.change]
            icon = _CHANGE_ICONS[d.change]
            severity = classify_severity(d.change, d.similarity, threshold)
            sev_cell = (
                f"[{_SEVERITY_COLORS[severity]}]{severity.value}[/{_SEVERITY_COLORS[severity]}]"
                if severity is not Severity.NONE
                else ""
            )

            # truncate long inputs for table display
            inp = d.input_text[:60] + "..." if len(d.input_text) > 60 else d.input_text

            table.add_row(
                str(i),
                f"[{color}]{icon}[/{color}]",
                inp,
                sev_cell,
                f"[{color}]{d.similarity:.1%}[/{color}]",
                f"{d.latency_delta_ms:+.0f}ms",
                f"{d.token_delta:+d}",
            )

        if table.row_count > 0:
            self.console.print(table)
        else:
            self.console.print("[dim]All cases unchanged.[/dim]")

    def print_detail(self, diff: CaseDiff, index: int = 0) -> None:
        """Print detailed side-by-side for a single case."""
        color = _CHANGE_COLORS[diff.change]
        self.console.print(f"\n[bold]Case {index}[/bold] [{color}]{diff.change.value}[/{color}]")
        self.console.print(f"[dim]Input:[/dim] {diff.input_text[:200]}")
        self.console.print(f"[dim]Similarity:[/dim] {diff.similarity:.1%}")

        # side by side outputs
        out_a = diff.output_a[:500] if diff.output_a else "(empty)"
        out_b = diff.output_b[:500] if diff.output_b else "(empty)"
        self.console.print(Panel(out_a, title="Prompt A", border_style="blue", width=80))
        self.console.print(Panel(out_b, title="Prompt B", border_style="magenta", width=80))

    def print_full(
        self,
        diffs: list[CaseDiff],
        summary: DiffSummary,
        verbose: bool = False,
        show_unchanged: bool = False,
        sort_by: str = "severity",
        threshold: float = DEFAULT_THRESHOLD,
    ) -> None:
        self.console.print()
        self.print_summary(summary)
        self.console.print()
        self.print_cases(diffs, show_unchanged=show_unchanged, sort_by=sort_by, threshold=threshold)

        if verbose:
            changed = [
                (i, d)
                for i, d in self._ordered_cases(diffs, sort_by)
                if d.change != ChangeType.UNCHANGED
            ]
            for i, d in changed:
                self.print_detail(d, index=i)


def render_markdown(
    diffs: list[CaseDiff],
    summary: DiffSummary,
    gates: dict | None = None,
    top_n: int = 10,
    title: str = "PromptDiff Report",
    threshold: float = DEFAULT_THRESHOLD,
) -> str:
    """Render diff results as a standalone Markdown report.

    Suitable for posting as a CI comment or PR artifact. No LLM calls.
    """
    lines = [f"# {title}", "", _headline(summary), ""]

    lines.append("| Metric | Value |")
    lines.append("| --- | --- |")
    lines.append(f"| Total cases | {summary.total} |")
    lines.append(f"| Unchanged | {summary.unchanged} |")
    lines.append(f"| Regressed | {summary.regressed} |")
    lines.append(f"| Improved | {summary.improved} |")
    lines.append(f"| Errors | {summary.errors} |")
    lines.append(f"| Avg similarity | {summary.avg_similarity:.2%} |")
    lines.append(f"| Avg latency delta | {summary.avg_latency_delta_ms:+.0f}ms |")
    lines.append(f"| Avg token delta | {summary.avg_token_delta:+.0f} |")
    lines.append("")

    if gates is not None:
        lines.append("## Regression budget")
        lines.append("")
        lines.append("Status: passed" if gates.get("passed", True) else "Status: failed")
        lines.append("")
        for failure in gates.get("failures") or []:
            lines.append(f"- {failure}")
        if gates.get("failures"):
            lines.append("")

    lines.append("## Top regressed cases")
    lines.append("")
    risky = [
        (i, d)
        for i, d in DiffReport._ordered_cases(diffs, "severity")
        if d.change in (ChangeType.REGRESSED, ChangeType.ERROR)
    ]
    if not risky:
        lines.append("No regressions.")
    else:
        phrase = _severity_phrase(severity_breakdown(diffs, threshold))
        if phrase:
            lines.append(f"Severity: {phrase}.")
            lines.append("")
        lines.append("| # | Input | Change | Severity | Similarity | Latency | Tokens |")
        lines.append("| --- | --- | --- | --- | --- | --- | --- |")
        for i, d in risky[:top_n]:
            severity = classify_severity(d.change, d.similarity, threshold)
            lines.append(
                f"| {i} | {_md_cell(d.input_text)} | {d.change.value} | {severity.value} | "
                f"{d.similarity:.1%} | {d.latency_delta_ms:+.0f}ms | {d.token_delta:+d} |"
            )

    return "\n".join(lines).rstrip() + "\n"


_HTML_STYLE = """
  body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         margin: 2rem auto; max-width: 960px; color: #1f2328; line-height: 1.5; }
  h1 { margin-bottom: 0.25rem; }
  .headline { font-size: 1.1rem; color: #444; margin-top: 0; }
  table { border-collapse: collapse; width: 100%; margin: 0.5rem 0 1.5rem; }
  th, td { border: 1px solid #d0d7de; padding: 0.4rem 0.6rem; text-align: left;
           vertical-align: top; font-size: 0.9rem; }
  table.summary { width: auto; }
  table.summary th { background: #f6f8fa; white-space: nowrap; }
  td.input { max-width: 28rem; word-break: break-word; white-space: pre-wrap; }
  tr.change-regressed { background: #fde7e7; }
  tr.change-error { background: #f6c9c9; }
  tr.change-improved { background: #e6f4ea; }
  .gate { font-weight: 600; }
  .gate-passed { color: #1a7f37; }
  .gate-failed { color: #cf222e; }
  ul { margin-top: 0.25rem; }
"""


def render_html(
    diffs: list[CaseDiff],
    summary: DiffSummary,
    gates: dict | None = None,
    title: str = "PromptDiff Report",
    threshold: float = DEFAULT_THRESHOLD,
) -> str:
    """Render diff results as a standalone, dependency-free HTML report.

    A single self-contained file (inline CSS, no external assets or JavaScript)
    suitable for sharing, archiving as a CI artifact, or opening in a browser for
    a richer human review than the Markdown report. Rows are colour-coded by
    change type and all case text is HTML-escaped. No LLM calls.
    """

    def esc(value: object) -> str:
        return html.escape(str(value))

    metrics = [
        ("Total cases", summary.total),
        ("Unchanged", summary.unchanged),
        ("Regressed", summary.regressed),
        ("Improved", summary.improved),
        ("Errors", summary.errors),
        ("Avg similarity", f"{summary.avg_similarity:.2%}"),
        ("Avg latency delta", f"{summary.avg_latency_delta_ms:+.0f}ms"),
        ("Avg token delta", f"{summary.avg_token_delta:+.0f}"),
    ]
    metric_rows = "".join(
        f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>" for label, value in metrics
    )

    gate_section = ""
    if gates is not None:
        status = "passed" if gates.get("passed", True) else "failed"
        items = "".join(f"<li>{esc(f)}</li>" for f in (gates.get("failures") or []))
        failures_html = f"<ul>{items}</ul>" if items else ""
        gate_section = (
            "<h2>Regression budget</h2>"
            f'<p class="gate gate-{status}">Status: {status}</p>{failures_html}'
        )

    case_rows = []
    for i, d in DiffReport._ordered_cases(diffs, "severity"):
        severity = classify_severity(d.change, d.similarity, threshold)
        case_rows.append(
            f'<tr class="change-{esc(d.change.value)}">'
            f"<td>{i}</td>"
            f'<td class="input">{esc(d.input_text)}</td>'
            f"<td>{esc(d.change.value)}</td>"
            f"<td>{esc(severity.value)}</td>"
            f"<td>{d.similarity:.1%}</td>"
            f"<td>{d.latency_delta_ms:+.0f}ms</td>"
            f"<td>{d.token_delta:+d}</td>"
            "</tr>"
        )
    cases_html = "".join(case_rows) or '<tr><td colspan="7">No cases.</td></tr>'

    parts = [
        "<!doctype html>",
        '<html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{esc(title)}</title>",
        f"<style>{_HTML_STYLE}</style>",
        "</head><body>",
        f"<h1>{esc(title)}</h1>",
        f'<p class="headline">{esc(_headline(summary))}</p>',
        "<h2>Summary</h2>",
        f'<table class="summary"><tbody>{metric_rows}</tbody></table>',
        gate_section,
        "<h2>Cases</h2>",
        '<table class="cases"><thead><tr><th>#</th><th>Input</th><th>Change</th>'
        "<th>Severity</th><th>Similarity</th><th>Latency</th><th>Tokens</th></tr></thead>",
        f"<tbody>{cases_html}</tbody></table>",
        "</body></html>",
    ]
    return "\n".join(parts) + "\n"


def render_junit_xml(
    diffs: list[CaseDiff],
    summary: DiffSummary,
    suite_name: str = "PromptDiff",
    threshold: float = DEFAULT_THRESHOLD,
) -> str:
    """Render diff results as JUnit XML.

    Lets CI systems that consume JUnit reports (GitLab ``artifacts:reports:junit``,
    Jenkins, CircleCI, GitHub test-reporter actions) surface each test case as a
    passed test, a failure (regression) or an error, alongside the existing exit
    code. Regressed cases become ``<failure>``, errored cases ``<error>``, and
    improved/unchanged cases pass. No LLM calls.
    """
    attrs = {
        "name": suite_name,
        "tests": str(summary.total),
        "failures": str(summary.regressed),
        "errors": str(summary.errors),
    }
    suite = ET.Element("testsuite", attrs)
    for index, d in enumerate(diffs, start=1):
        case = ET.SubElement(
            suite,
            "testcase",
            {"classname": suite_name, "name": _junit_case_name(index, d.input_text)},
        )
        if d.change == ChangeType.ERROR:
            node = ET.SubElement(
                case, "error", {"type": "error", "message": _junit_error_message(d)}
            )
            node.text = _junit_error_detail(d)
        elif d.change == ChangeType.REGRESSED:
            severity = classify_severity(d.change, d.similarity, threshold)
            node = ET.SubElement(
                case,
                "failure",
                {
                    "type": "regression",
                    "message": f"{severity.value} regression: similarity {d.similarity:.1%}",
                },
            )
            node.text = _junit_failure_detail(d)
        # improved / unchanged cases pass with no child element

    root = ET.Element("testsuites", attrs)
    root.append(suite)
    ET.indent(root)
    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="utf-8"?>\n' + body + "\n"


def _junit_case_name(index: int, input_text: str) -> str:
    snippet = " ".join(input_text.split())
    if len(snippet) > 60:
        snippet = snippet[:57] + "..."
    return f"case {index}: {snippet}" if snippet else f"case {index}"


def _junit_failure_detail(d: CaseDiff) -> str:
    parts = [
        f"similarity: {d.similarity:.1%}",
        f"latency delta: {d.latency_delta_ms:+.0f}ms",
        f"token delta: {d.token_delta:+d}",
    ]
    if d.judge_verdict:
        parts.append(f"judge: {d.judge_verdict}")
    if d.judge_reason:
        parts.append(f"reason: {d.judge_reason}")
    return "\n".join(parts)


def _junit_error_message(d: CaseDiff) -> str:
    if d.error_a and d.error_b:
        return "both prompt versions errored"
    if d.error_a:
        return "prompt A errored"
    if d.error_b:
        return "prompt B errored"
    return "prompt errored"


def _junit_error_detail(d: CaseDiff) -> str:
    parts = []
    if d.error_a:
        parts.append(f"A: {d.error_a}")
    if d.error_b:
        parts.append(f"B: {d.error_b}")
    return "\n".join(parts)


def _headline(summary: DiffSummary) -> str:
    parts = []
    if summary.unchanged:
        parts.append(f"{summary.unchanged} unchanged")
    if summary.regressed:
        parts.append(f"{summary.regressed} regressed")
    if summary.improved:
        parts.append(f"{summary.improved} improved")
    if summary.errors:
        parts.append(f"{summary.errors} errors")
    return f"**{summary.total} cases**: " + (", ".join(parts) if parts else "no differences")


def _md_cell(text: str, width: int = 60) -> str:
    """Flatten text into a single Markdown table cell."""
    cell = " ".join(text.split())
    if len(cell) > width:
        cell = cell[: width - 3] + "..."
    return cell.replace("|", "\\|")
