"""Compare two benchmark reports question by question (Week 4, ADR-0013).

Derived label sets keep question IDs, so runs with different chunking compare on the same
questions. Per-question changes matter as much as the mean: a variant that fixes three
questions and breaks three others is not an improvement.
"""

from pydantic import BaseModel, ConfigDict

from enterprise_knowledge.evaluation.benchmark import BenchmarkReport


class ReportComparison(BaseModel):
    model_config = ConfigDict(frozen=True)

    baseline: str
    candidate: str
    recall_at_k_delta: dict[int, float | None]
    mrr_delta: float | None
    improved: list[str]  # questions whose reciprocal rank rose
    worsened: list[str]


def compare_reports(baseline: BenchmarkReport, candidate: BenchmarkReport) -> ReportComparison:
    before = {r.question_id: r.reciprocal_rank for r in baseline.results}
    after = {r.question_id: r.reciprocal_rank for r in candidate.results}
    if before.keys() != after.keys():
        raise ValueError("reports must cover the same questions")
    scored = [q for q in before if before[q] is not None and after[q] is not None]
    return ReportComparison(
        baseline=_name(baseline),
        candidate=_name(candidate),
        recall_at_k_delta={
            k: _delta(baseline.recall_at_k.get(k), candidate.recall_at_k.get(k))
            for k in sorted(set(baseline.recall_at_k) & set(candidate.recall_at_k))
        },
        mrr_delta=_delta(baseline.mrr, candidate.mrr),
        improved=[q for q in scored if (after[q] or 0.0) > (before[q] or 0.0)],
        worsened=[q for q in scored if (after[q] or 0.0) < (before[q] or 0.0)],
    )


def _name(report: BenchmarkReport) -> str:
    return report.experiment.name if report.experiment else report.dataset_version


def _delta(before: float | None, after: float | None) -> float | None:
    return None if before is None or after is None else after - before
