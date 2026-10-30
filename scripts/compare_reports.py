"""Compare benchmark reports against the first one (Week 4, ADR-0013).

    uv run python scripts/compare_reports.py docs/evaluation/benchmark-v2-baseline-fpt-*.json \
        docs/evaluation/benchmark-v2-packed1200-packed-1200-fpt-*.json

Prints overall and per-type Recall@1 and MRR for each report, then, for every report after
the first, the questions whose reciprocal rank improved or worsened. Reports must cover the
same question IDs, which derived label sets guarantee.
"""

import argparse
import sys
from pathlib import Path

from enterprise_knowledge.evaluation.benchmark import BenchmarkReport, QuestionType
from enterprise_knowledge.evaluation.comparison import compare_reports

COLUMNS = (QuestionType.CROSS_LINGUAL, QuestionType.NEAR_DUPLICATE, QuestionType.MULTI_DOCUMENT)


def pct(value: float | None) -> str:
    return "  n/a" if value is None else f"{value:5.1%}"


def describe(report: BenchmarkReport) -> str:
    experiment = report.experiment
    name = experiment.name if experiment else report.dataset_version
    header = "" if experiment is None or experiment.embedding_header else ", no header"
    return f"{name} [{report.dataset_version}, {report.embedding_model}{header}]"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "reports", nargs="+", type=Path, help="report JSON files; first is baseline"
    )
    args = parser.parse_args()
    reports = [BenchmarkReport.model_validate_json(p.read_text("utf-8")) for p in args.reports]

    print(
        f"{'experiment':58}  R@1     R@3     MRR   "
        + "".join(f" {t.value[:12]:>12} R@1" for t in COLUMNS)
    )
    for report in reports:
        print(
            f"{describe(report):58} {pct(report.recall_at_k.get(1))}  "
            f"{pct(report.recall_at_k.get(3))}  {pct(report.mrr)}"
            + "".join(f"        {pct(report.by_type[t].recall_at_k.get(1))}" for t in COLUMNS)
        )

    for candidate in reports[1:]:
        comparison = compare_reports(reports[0], candidate)
        print(
            f"\n{comparison.candidate} vs {comparison.baseline}: "
            f"{len(comparison.improved)} improved, {len(comparison.worsened)} worsened"
        )
        print(f"  improved: {', '.join(comparison.improved) or '-'}")
        print(f"  worsened: {', '.join(comparison.worsened) or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
