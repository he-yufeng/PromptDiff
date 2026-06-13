"""CLI interface for PromptDiff."""

from __future__ import annotations

import asyncio
import sys

import click
from rich.console import Console

from promptdiff.diff import ChangeType, PromptDiff
from promptdiff.judge import judge_case
from promptdiff.loader import load_prompt, load_test_cases
from promptdiff.report import DiffReport
from promptdiff.runner import PromptRunner, RunConfig

console = Console()


@click.group()
@click.version_option(package_name="promptdiff")
def main():
    """PromptDiff — semantic diff for LLM prompts."""
    pass


@main.command()
@click.argument("prompt", type=click.Path(exists=True))
@click.argument("test_cases", type=click.Path(exists=True))
@click.option("--min-cases", default=1, type=int, help="Minimum number of test cases required.")
def validate(prompt: str, test_cases: str, min_cases: int):
    """Validate prompt and test-case files without calling an LLM."""
    if min_cases <= 0:
        raise click.UsageError("--min-cases must be greater than zero")

    try:
        prompt_text = load_prompt(prompt)
        inputs = load_test_cases(test_cases)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if not prompt_text:
        raise click.ClickException("Prompt file is empty.")
    if len(inputs) < min_cases:
        raise click.ClickException(
            f"Only found {len(inputs)} test case(s), but --min-cases is {min_cases}."
        )

    console.print("[green]PromptDiff inputs look valid.[/green]")
    console.print(f"[bold]Prompt chars:[/bold] {len(prompt_text):,}")
    console.print(f"[bold]Test cases:[/bold] {len(inputs):,}")


@main.command()
@click.argument("prompt_a", type=click.Path(exists=True))
@click.argument("prompt_b", type=click.Path(exists=True))
@click.argument("test_cases", type=click.Path(exists=True))
@click.option("--model", "-m", default="gpt-4o-mini", help="Model to use for running prompts.")
@click.option("--base-url", default=None, help="Custom OpenAI-compatible API base URL.")
@click.option("--api-key", default=None, help="API key (defaults to OPENAI_API_KEY env var).")
@click.option("--threshold", "-t", default=0.85, type=float, help="Similarity threshold for 'unchanged' (0-1).")
@click.option("--judge/--no-judge", default=False, help="Use LLM-as-judge to classify changes as improved/regressed.")
@click.option("--judge-model", default="gpt-4o-mini", help="Model for the judge.")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed output for changed cases.")
@click.option("--show-unchanged", is_flag=True, help="Include unchanged cases in the report.")
@click.option(
    "--sort",
    "sort_by",
    type=click.Choice(["severity", "input"]),
    default="severity",
    show_default=True,
    help="Case ordering in terminal reports.",
)
@click.option("--json-output", "-o", type=click.Path(), default=None, help="Write JSON results to file.")
@click.option("--concurrency", "-c", default=5, type=int, help="Max concurrent API calls.")
@click.option("--no-semantic", is_flag=True, help="Use lexical similarity instead of embeddings.")
@click.option("--fail-on-regression", is_flag=True, help="Exit with code 1 if any regressions found (for CI).")
@click.option("--fail-on-error", is_flag=True, help="Exit with code 1 if any prompt run errors occur (for CI).")
def compare(
    prompt_a: str,
    prompt_b: str,
    test_cases: str,
    model: str,
    base_url: str | None,
    api_key: str | None,
    threshold: float,
    judge: bool,
    judge_model: str,
    verbose: bool,
    show_unchanged: bool,
    sort_by: str,
    json_output: str | None,
    concurrency: int,
    no_semantic: bool,
    fail_on_regression: bool,
    fail_on_error: bool,
):
    """Compare two prompt versions against test cases.

    PROMPT_A and PROMPT_B are text files containing the system prompts.
    TEST_CASES is a file with test inputs (.jsonl, .json, .yaml, or .txt).
    """
    text_a = load_prompt(prompt_a)
    text_b = load_prompt(prompt_b)
    inputs = load_test_cases(test_cases)

    if not inputs:
        console.print("[red]No test cases found.[/red]")
        sys.exit(1)

    console.print(f"[bold]Running {len(inputs)} test cases through [blue]{model}[/blue]...[/bold]")

    config = RunConfig(
        model=model,
        base_url=base_url,
        api_key=api_key,
        concurrency=concurrency,
    )
    runner = PromptRunner(config)

    # run both prompt versions
    results_a, results_b = asyncio.run(_run_both(runner, text_a, text_b, inputs))

    # compute diffs
    differ = PromptDiff(threshold=threshold, use_semantic=not no_semantic)
    diffs, summary = differ.compare_batch(results_a, results_b)

    # optionally run judge on changed cases
    if judge:
        console.print(f"[bold]Judging {summary.regressed} changed cases with [blue]{judge_model}[/blue]...[/bold]")
        from openai import AsyncOpenAI as _Client

        judge_kwargs = {}
        if base_url:
            judge_kwargs["base_url"] = base_url
        if api_key:
            judge_kwargs["api_key"] = api_key
        client = _Client(**judge_kwargs)
        diffs = asyncio.run(_judge_all(diffs, client, judge_model))

        # recompute summary after judging
        summary.improved = sum(1 for d in diffs if d.change == ChangeType.IMPROVED)
        summary.regressed = sum(1 for d in diffs if d.change == ChangeType.REGRESSED)
        summary.unchanged = sum(1 for d in diffs if d.change == ChangeType.UNCHANGED)

    # output
    report = DiffReport(console)
    report.print_full(
        diffs,
        summary,
        verbose=verbose,
        show_unchanged=show_unchanged,
        sort_by=sort_by,
    )

    if json_output:
        from pathlib import Path

        Path(json_output).write_text(differ.to_json(diffs, summary), encoding="utf-8")
        console.print(f"\n[dim]JSON results written to {json_output}[/dim]")

    if (fail_on_regression and summary.regressed > 0) or (fail_on_error and summary.errors > 0):
        sys.exit(1)


async def _run_both(
    runner: PromptRunner, prompt_a: str, prompt_b: str, inputs: list[str]
) -> tuple[list, list]:
    """Run both prompts concurrently."""
    a, b = await asyncio.gather(
        runner.run_batch(prompt_a, inputs),
        runner.run_batch(prompt_b, inputs),
    )
    return a, b


async def _judge_all(diffs, client, model):
    """Run the judge on all changed cases."""
    tasks = []
    for d in diffs:
        if d.change == ChangeType.REGRESSED:
            tasks.append(judge_case(d, client, model))
        else:
            async def _identity(x=d):
                return x
            tasks.append(_identity())
    return await asyncio.gather(*tasks)


if __name__ == "__main__":
    main()
