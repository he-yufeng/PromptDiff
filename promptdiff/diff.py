"""Compare two sets of prompt results and produce a semantic diff."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum

from promptdiff.runner import RunResult


class ChangeType(str, Enum):
    IMPROVED = "improved"
    REGRESSED = "regressed"
    UNCHANGED = "unchanged"
    ERROR = "error"


class Severity(str, Enum):
    """How serious a behavioural change is, for triage."""

    NONE = "none"
    MINOR = "minor"
    MODERATE = "moderate"
    MAJOR = "major"


def classify_severity(change: ChangeType, similarity: float, threshold: float) -> Severity:
    """Grade a single case so reviewers know which regressions to look at first.

    Errors are always major. Regressions are graded by how far the output
    similarity fell below the "unchanged" threshold, normalised by the threshold
    so the bands track whatever cutoff a run used: a drop of up to a third of the
    way to zero is minor, up to two thirds is moderate, and anything worse is
    major. Unchanged and improved cases carry no severity.
    """
    if change == ChangeType.ERROR:
        return Severity.MAJOR
    if change != ChangeType.REGRESSED:
        return Severity.NONE
    if threshold <= 0:
        return Severity.MAJOR
    drop = (threshold - similarity) / threshold
    if drop <= 1 / 3:
        return Severity.MINOR
    if drop <= 2 / 3:
        return Severity.MODERATE
    return Severity.MAJOR


def severity_breakdown(diffs: list[CaseDiff], threshold: float) -> dict[str, int]:
    """Count regressed and errored cases by severity (worst first)."""
    counts = {Severity.MAJOR.value: 0, Severity.MODERATE.value: 0, Severity.MINOR.value: 0}
    for d in diffs:
        sev = classify_severity(d.change, d.similarity, threshold)
        if sev is not Severity.NONE:
            counts[sev.value] += 1
    return counts


@dataclass
class CaseDiff:
    """Diff for a single test case."""

    input_text: str
    output_a: str
    output_b: str
    change: ChangeType
    similarity: float  # 0.0 to 1.0
    latency_delta_ms: float  # positive = B slower
    token_delta: int  # positive = B uses more

    # if a judge was used
    judge_verdict: str | None = None
    judge_reason: str | None = None
    error_a: str | None = None
    error_b: str | None = None


@dataclass
class DiffSummary:
    """Aggregate stats across all test cases."""

    total: int
    improved: int
    regressed: int
    unchanged: int
    errors: int
    avg_similarity: float
    avg_latency_delta_ms: float
    avg_token_delta: float


def evaluate_gates(
    summary: DiffSummary,
    max_regression_rate: float | None = None,
    max_avg_latency_increase_ms: float | None = None,
    max_avg_token_increase: float | None = None,
    min_avg_similarity: float | None = None,
    max_error_rate: float | None = None,
) -> dict:
    """Evaluate CI budgets against the aggregate diff."""
    regression_rate = summary.regressed / max(summary.total, 1)
    error_rate = summary.errors / max(summary.total, 1)
    failures = []
    if max_regression_rate is not None and regression_rate > max_regression_rate:
        failures.append(
            f"regression rate {regression_rate:.1%} exceeds {max_regression_rate:.1%}"
        )
    if (
        max_avg_latency_increase_ms is not None
        and summary.avg_latency_delta_ms > max_avg_latency_increase_ms
    ):
        failures.append(
            f"average latency increase {summary.avg_latency_delta_ms:.1f}ms exceeds "
            f"{max_avg_latency_increase_ms:.1f}ms"
        )
    if max_avg_token_increase is not None and summary.avg_token_delta > max_avg_token_increase:
        failures.append(
            f"average token increase {summary.avg_token_delta:.1f} exceeds "
            f"{max_avg_token_increase:.1f}"
        )
    if min_avg_similarity is not None and summary.avg_similarity < min_avg_similarity:
        failures.append(
            f"average similarity {summary.avg_similarity:.1%} is below {min_avg_similarity:.1%}"
        )
    if max_error_rate is not None and error_rate > max_error_rate:
        failures.append(f"error rate {error_rate:.1%} exceeds {max_error_rate:.1%}")
    return {
        "passed": not failures,
        "regression_rate": round(regression_rate, 4),
        "error_rate": round(error_rate, 4),
        "avg_similarity": summary.avg_similarity,
        "limits": {
            "max_regression_rate": max_regression_rate,
            "max_avg_latency_increase_ms": max_avg_latency_increase_ms,
            "max_avg_token_increase": max_avg_token_increase,
            "min_avg_similarity": min_avg_similarity,
            "max_error_rate": max_error_rate,
        },
        "failures": failures,
    }


def diffs_from_payload(payload: dict) -> tuple[list[CaseDiff], DiffSummary]:
    """Reconstruct diffs and summary from a serialized results payload.

    Inverse of PromptDiff.to_json, used to render reports from a saved run
    without re-calling the model.
    """
    s = payload["summary"]
    summary = DiffSummary(
        total=s["total"],
        improved=s["improved"],
        regressed=s["regressed"],
        unchanged=s["unchanged"],
        errors=s["errors"],
        avg_similarity=s["avg_similarity"],
        avg_latency_delta_ms=s["avg_latency_delta_ms"],
        avg_token_delta=s["avg_token_delta"],
    )
    diffs = [
        CaseDiff(
            input_text=c["input"],
            output_a=c.get("output_a", ""),
            output_b=c.get("output_b", ""),
            change=ChangeType(c["change"]),
            similarity=c["similarity"],
            latency_delta_ms=c["latency_delta_ms"],
            token_delta=c["token_delta"],
            judge_verdict=c.get("judge_verdict"),
            judge_reason=c.get("judge_reason"),
            error_a=c.get("error_a"),
            error_b=c.get("error_b"),
        )
        for c in payload["cases"]
    ]
    return diffs, summary


class PromptDiff:
    """Compute behavioral diffs between two prompt versions."""

    def __init__(
        self,
        threshold: float = 0.85,
        use_semantic: bool = True,
    ):
        self.threshold = threshold
        self.use_semantic = use_semantic
        self._embedder = None

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer("all-MiniLM-L6-v2")
            except ImportError:
                return None
        return self._embedder

    def _semantic_similarity(self, text_a: str, text_b: str) -> float:
        """Compute cosine similarity between two texts."""
        # Identical outputs are unchanged — check this first so two empty (or
        # whitespace-only) outputs score 1.0 like the lexical fallback does,
        # instead of being flagged as a regression.
        if text_a.strip() == text_b.strip():
            return 1.0

        if not text_a or not text_b:
            return 0.0

        if not self.use_semantic:
            return self._lexical_similarity(text_a, text_b)

        embedder = self._get_embedder()
        if embedder is None:
            return self._lexical_similarity(text_a, text_b)

        embs = embedder.encode([text_a, text_b], normalize_embeddings=True)
        score = float(embs[0] @ embs[1])
        return max(0.0, min(1.0, score))

    @staticmethod
    def _lexical_similarity(text_a: str, text_b: str) -> float:
        """Jaccard similarity as fallback."""
        words_a = set(text_a.lower().split())
        words_b = set(text_b.lower().split())
        if not words_a and not words_b:
            return 1.0
        if not words_a or not words_b:
            return 0.0
        return len(words_a & words_b) / len(words_a | words_b)

    def compare_pair(self, result_a: RunResult, result_b: RunResult) -> CaseDiff:
        """Compare a single test case across two prompt versions."""
        if result_a.error or result_b.error:
            return CaseDiff(
                input_text=result_a.input_text,
                output_a=result_a.output,
                output_b=result_b.output,
                change=ChangeType.ERROR,
                similarity=0.0,
                latency_delta_ms=result_b.latency_ms - result_a.latency_ms,
                token_delta=(result_b.tokens_out - result_a.tokens_out),
                error_a=result_a.error,
                error_b=result_b.error,
            )

        sim = self._semantic_similarity(result_a.output, result_b.output)

        if sim >= self.threshold:
            change = ChangeType.UNCHANGED
        else:
            # without a judge we can't tell improved vs regressed,
            # so we mark it as "regressed" (conservative — behavior changed)
            change = ChangeType.REGRESSED

        return CaseDiff(
            input_text=result_a.input_text,
            output_a=result_a.output,
            output_b=result_b.output,
            change=change,
            similarity=round(sim, 4),
            latency_delta_ms=round(result_b.latency_ms - result_a.latency_ms, 1),
            token_delta=result_b.tokens_out - result_a.tokens_out,
        )

    def compare_batch(
        self, results_a: list[RunResult], results_b: list[RunResult]
    ) -> tuple[list[CaseDiff], DiffSummary]:
        """Compare all test cases and produce diffs + summary."""
        assert len(results_a) == len(results_b), "Result lists must have equal length"

        diffs = [self.compare_pair(a, b) for a, b in zip(results_a, results_b)]

        improved = sum(1 for d in diffs if d.change == ChangeType.IMPROVED)
        regressed = sum(1 for d in diffs if d.change == ChangeType.REGRESSED)
        unchanged = sum(1 for d in diffs if d.change == ChangeType.UNCHANGED)
        errors = sum(1 for d in diffs if d.change == ChangeType.ERROR)

        avg_sim = sum(d.similarity for d in diffs) / len(diffs) if diffs else 0.0
        avg_lat = sum(d.latency_delta_ms for d in diffs) / len(diffs) if diffs else 0.0
        avg_tok = sum(d.token_delta for d in diffs) / len(diffs) if diffs else 0.0

        summary = DiffSummary(
            total=len(diffs),
            improved=improved,
            regressed=regressed,
            unchanged=unchanged,
            errors=errors,
            avg_similarity=round(avg_sim, 4),
            avg_latency_delta_ms=round(avg_lat, 1),
            avg_token_delta=round(avg_tok, 1),
        )

        return diffs, summary

    def to_json(
        self,
        diffs: list[CaseDiff],
        summary: DiffSummary,
        gates: dict | None = None,
    ) -> str:
        """Serialize diff results to JSON."""
        payload = {
            "threshold": self.threshold,
            "summary": {
                "total": summary.total,
                "improved": summary.improved,
                "regressed": summary.regressed,
                "unchanged": summary.unchanged,
                "errors": summary.errors,
                "avg_similarity": summary.avg_similarity,
                "avg_latency_delta_ms": summary.avg_latency_delta_ms,
                "avg_token_delta": summary.avg_token_delta,
            },
            "cases": [
                {
                    "input": d.input_text,
                    "output_a": d.output_a,
                    "output_b": d.output_b,
                    "change": d.change.value,
                    "similarity": d.similarity,
                    "latency_delta_ms": d.latency_delta_ms,
                    "token_delta": d.token_delta,
                    "judge_verdict": d.judge_verdict,
                    "judge_reason": d.judge_reason,
                    "error_a": d.error_a,
                    "error_b": d.error_b,
                }
                for d in diffs
            ],
        }
        if gates is not None:
            payload["gates"] = gates
        return json.dumps(payload, indent=2)
