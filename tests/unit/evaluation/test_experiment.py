"""Experiment configurations and report comparison (Week 4, ADR-0013)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from enterprise_knowledge.evaluation.benchmark import (
    BenchmarkReport,
    QuestionResult,
    QuestionType,
    TypeBreakdown,
)
from enterprise_knowledge.evaluation.comparison import compare_reports
from enterprise_knowledge.evaluation.experiment import ExperimentConfig, load_experiment
from enterprise_knowledge.ingestion.chunking import ChunkingSettings

CONFIG = """
name = "packed-1200"
description = "Short sections share a chunk."
corpus = "v2"
benchmark = "v2-packed1200"
embedding = "fpt"
embedding_header = false
k_values = [1, 3]
"""


def test_experiment_config_loads_from_toml(tmp_path: Path) -> None:
    path = tmp_path / "packed.toml"
    path.write_text(CONFIG, encoding="utf-8")

    config = load_experiment(path)

    assert config == ExperimentConfig(
        name="packed-1200",
        description="Short sections share a chunk.",
        corpus="v2",
        benchmark="v2-packed1200",
        embedding="fpt",
        embedding_header=False,
        k_values=(1, 3),
    )


def test_defaults_are_the_production_settings() -> None:
    config = ExperimentConfig(name="baseline", corpus="v2", benchmark="v2", embedding="hashing")

    assert config.embedding_header
    assert config.k_values == (1, 3, 5, 10)
    assert (config.retrieval, config.rrf_k, config.candidates) == ("vector", 60, 50)


def test_hybrid_retrieval_settings_are_part_of_the_experiment() -> None:
    config = ExperimentConfig.model_validate(
        {
            "name": "hybrid",
            "corpus": "v2",
            "benchmark": "v2",
            "embedding": "fpt",
            "retrieval": "hybrid",
            "rrf_k": 30,
            "candidates": 40,
        }
    )

    assert config.retrieval_settings().model_dump() == {
        "mode": "hybrid",
        "rrf_k": 30,
        "candidates": 40,
    }


def test_unknown_experiment_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "typo.toml"
    path.write_text(CONFIG + 'embeding_model = "other"\n', encoding="utf-8")

    with pytest.raises(ValidationError, match="embeding_model"):
        load_experiment(path)


@pytest.mark.parametrize("k_values", [[], [0, 3], [3, 3]], ids=["empty", "zero", "repeated"])
def test_k_values_must_be_positive_and_distinct(k_values: list[int]) -> None:
    with pytest.raises(ValidationError, match="k_values"):
        ExperimentConfig(
            name="x", corpus="v2", benchmark="v2", embedding="hashing", k_values=tuple(k_values)
        )


def report(name: str, ranks: dict[str, float | None]) -> BenchmarkReport:
    """A minimal report whose answerable questions have the given reciprocal ranks."""
    results = [
        QuestionResult(
            question_id=question_id,
            types=[QuestionType.ENGLISH],
            answerable=rank is not None,
            ranked=[],
            recall_at_k={1: float(rank == 1.0)} if rank is not None else None,
            reciprocal_rank=rank,
        )
        for question_id, rank in ranks.items()
    ]
    answerable = [r.reciprocal_rank for r in results if r.reciprocal_rank is not None]
    mrr = sum(answerable) / len(answerable)
    return BenchmarkReport(
        started_at=datetime(2026, 10, 30, tzinfo=UTC),
        dataset_version="v2",
        corpus_manifest_sha256="0" * 64,
        chunking=ChunkingSettings(),
        embedding_model="fake",
        k_values=[1],
        questions=len(results),
        answerable=len(answerable),
        unanswerable=len(results) - len(answerable),
        access_violations=0,
        recall_at_k={1: sum(1.0 for r in answerable if r == 1.0) / len(answerable)},
        mrr=mrr,
        by_type={
            t: TypeBreakdown(questions=0, answerable=0, recall_at_k={1: None}, mrr=None)
            for t in QuestionType
        },
        top_score_answerable_mean=None,
        top_score_unanswerable_mean=None,
        results=results,
        experiment=ExperimentConfig(name=name, corpus="v2", benchmark="v2", embedding="hashing"),
    )


def test_comparison_lists_questions_that_improved_and_worsened() -> None:
    baseline = report("baseline", {"q1": 1.0, "q2": 0.5, "q3": 0.25, "q4": None})
    candidate = report("candidate", {"q1": 0.5, "q2": 0.5, "q3": 1.0, "q4": None})

    comparison = compare_reports(baseline, candidate)

    assert (comparison.baseline, comparison.candidate) == ("baseline", "candidate")
    assert comparison.improved == ["q3"]
    assert comparison.worsened == ["q1"]
    assert comparison.mrr_delta == pytest.approx((2.0 - 1.75) / 3)
    assert comparison.recall_at_k_delta == {1: pytest.approx(0.0)}


def test_reports_over_different_questions_cannot_be_compared() -> None:
    with pytest.raises(ValueError, match="same questions"):
        compare_reports(report("a", {"q1": 1.0}), report("b", {"q2": 1.0}))
