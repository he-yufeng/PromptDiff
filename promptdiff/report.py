"""Rich terminal report for prompt diffs."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from promptdiff.diff import CaseDiff, ChangeType, DiffSummary

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
    ) -> None:
        table = Table(show_header=True, header_style="bold", expand=True)
        table.add_column("#", width=3, justify="right")
        table.add_column("", width=1)  # icon
        table.add_column("Input", ratio=2)
        table.add_column("Similarity", width=10, justify="right")
        table.add_column("Latency", width=9, justify="right")
        table.add_column("Tokens", width=8, justify="right")

        for i, d in self._ordered_cases(diffs, sort_by):
            if d.change == ChangeType.UNCHANGED and not show_unchanged:
                continue

            color = _CHANGE_COLORS[d.change]
            icon = _CHANGE_ICONS[d.change]

            # truncate long inputs for table display
            inp = d.input_text[:60] + "..." if len(d.input_text) > 60 else d.input_text

            table.add_row(
                str(i),
                f"[{color}]{icon}[/{color}]",
                inp,
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
    ) -> None:
        self.console.print()
        self.print_summary(summary)
        self.console.print()
        self.print_cases(diffs, show_unchanged=show_unchanged, sort_by=sort_by)

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
        lines.append("| # | Input | Change | Similarity | Latency | Tokens |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for i, d in risky[:top_n]:
            lines.append(
                f"| {i} | {_md_cell(d.input_text)} | {d.change.value} | "
                f"{d.similarity:.1%} | {d.latency_delta_ms:+.0f}ms | {d.token_delta:+d} |"
            )

    return "\n".join(lines).rstrip() + "\n"


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
