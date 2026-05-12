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
        if not text_a or not text_b:
            return 0.0

        if text_a.strip() == text_b.strip():
            return 1.0

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
        self, diffs: list[CaseDiff], summary: DiffSummary
    ) -> str:
        """Serialize diff results to JSON."""
        return json.dumps(
            {
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
            },
            indent=2,
        )
