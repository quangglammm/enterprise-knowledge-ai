"""Judge calibration (ADR-0015): how often the judge agrees with hand-labelled verdicts.

The judge is the same model that writes the answers (the only one the account serves), so
its verdicts are evidence only as far as this agreement goes. Each case is either a
correctness case (answer against a reference) or a grounding case (answer against
evidence, with the labels the answer cited). Reports keep verdicts, not text.
"""

import hashlib
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from enterprise_knowledge.domain.access import AccessPolicy
from enterprise_knowledge.domain.documents import Language, SourceLocation
from enterprise_knowledge.domain.errors import DomainError
from enterprise_knowledge.domain.ids import ChunkId, DocumentId, GroupId, TenantId
from enterprise_knowledge.domain.retrieval import RetrievedEvidence
from enterprise_knowledge.evaluation.judge import JUDGE_PROMPT_VERSION, AnswerJudge, Correctness
from enterprise_knowledge.generation.prompts import evidence_label

_CALIBRATION_ACCESS = AccessPolicy(
    tenant_id=TenantId("judge-calibration"), allowed_groups=frozenset({GroupId("calibration")})
)


class CalibrationEvidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1)
    section: str | None = None
    text: str = Field(min_length=1)


class CalibrationCase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(pattern=r"^(corr|grnd)-(vi|en)-\d{2}$")
    kind: Literal["correctness", "grounding"]
    language: Literal["vi", "en"]
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    note: str = Field(min_length=1)  # what the case tests, for reviewers
    reference: str | None = None
    expect_verdict: Correctness | None = None
    evidence: list[CalibrationEvidence] = Field(default_factory=list, max_length=8)
    cited: list[str] = Field(default_factory=list)
    expect_faithful: bool | None = None
    expect_citation_supported: bool | None = None

    @model_validator(mode="after")
    def _expectations_match_kind(self) -> Self:
        if self.kind == "correctness":
            if self.reference is None or self.expect_verdict is None:
                raise ValueError(f"{self.id}: correctness cases need reference and expect_verdict")
            return self
        if not self.evidence:
            raise ValueError(f"{self.id}: grounding cases need evidence")
        labels = {evidence_label(i) for i in range(len(self.evidence))}
        if not self.cited or not set(self.cited) <= labels:
            raise ValueError(f"{self.id}: cited must be labels among {sorted(labels)}")
        if self.expect_faithful is None or self.expect_citation_supported is None:
            raise ValueError(f"{self.id}: grounding cases need both expectations")
        if self.expect_citation_supported and not self.expect_faithful:
            raise ValueError(f"{self.id}: citation support implies faithfulness")
        return self

    def retrieved(self) -> tuple[RetrievedEvidence, ...]:
        return tuple(
            RetrievedEvidence(
                chunk_id=ChunkId(f"{self.id}-e{i + 1}"),
                document_id=DocumentId(self.id),
                document_version=1,
                title=item.title,
                text=item.text,
                score=1.0,
                source=SourceLocation(section=item.section),
                access=_CALIBRATION_ACCESS,
                language=Language(self.language),
            )
            for i, item in enumerate(self.evidence)
        )


class CalibrationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    case_id: str
    kind: str
    expected: str  # "correct", or "faithful=True citation_supported=False"
    judged: str | None = None
    agrees: bool | None = None  # None when the judge failed
    faithful_agrees: bool | None = None
    citation_agrees: bool | None = None
    judge_model: str | None = None
    error_category: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class CalibrationReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    started_at: datetime
    dataset_sha256: str
    judge_model: str | None
    judge_prompt_version: str = JUDGE_PROMPT_VERSION
    cases: int
    judge_errors: int
    correctness_agreement: float | None
    faithfulness_agreement: float | None
    citation_support_agreement: float | None
    total_input_tokens: int
    total_output_tokens: int
    outcomes: list[CalibrationOutcome]


def load_calibration(path: Path) -> list[CalibrationCase]:
    cases = [
        CalibrationCase.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = [c.id for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate calibration case ids")
    return cases


def dataset_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run_calibration(
    cases: Sequence[CalibrationCase], judge: AnswerJudge, *, dataset_sha256: str
) -> CalibrationReport:
    started_at = datetime.now(UTC)
    outcomes = [await _judge_case(case, judge) for case in cases]
    correctness = [o for o in outcomes if o.kind == "correctness"]
    grounding = [o for o in outcomes if o.kind == "grounding"]
    return CalibrationReport(
        started_at=started_at,
        dataset_sha256=dataset_sha256,
        judge_model=next((o.judge_model for o in outcomes if o.judge_model), None),
        cases=len(outcomes),
        judge_errors=sum(1 for o in outcomes if o.error_category is not None),
        correctness_agreement=_rate(o.agrees for o in correctness),
        faithfulness_agreement=_rate(o.faithful_agrees for o in grounding),
        citation_support_agreement=_rate(o.citation_agrees for o in grounding),
        total_input_tokens=sum(o.input_tokens for o in outcomes),
        total_output_tokens=sum(o.output_tokens for o in outcomes),
        outcomes=outcomes,
    )


async def _judge_case(case: CalibrationCase, judge: AnswerJudge) -> CalibrationOutcome:
    row = {"case_id": case.id, "kind": case.kind, "expected": _expected(case)}
    try:
        if case.kind == "correctness":
            verdict = await judge.correctness(
                question=case.question, reference=_required(case.reference), answer=case.answer
            )
        else:
            grounding = await judge.grounding(
                question=case.question,
                answer=case.answer,
                evidence=case.retrieved(),
                cited=case.cited,
            )
    except DomainError as exc:  # provider and judge failures alike are recorded, not raised
        return CalibrationOutcome(**row, error_category=exc.category)

    if case.kind == "correctness":
        return CalibrationOutcome(
            **row,
            judged=verdict.verdict.value,
            agrees=verdict.verdict is case.expect_verdict,
            judge_model=verdict.model_id,
            input_tokens=verdict.input_tokens,
            output_tokens=verdict.output_tokens,
        )
    faithful = grounding.faithful is case.expect_faithful
    cited = grounding.citation_supported is case.expect_citation_supported
    return CalibrationOutcome(
        **row,
        judged=_grounding_label(grounding.faithful, grounding.citation_supported),
        agrees=faithful and cited,
        faithful_agrees=faithful,
        citation_agrees=cited,
        judge_model=grounding.model_id,
        input_tokens=grounding.input_tokens,
        output_tokens=grounding.output_tokens,
    )


def _expected(case: CalibrationCase) -> str:
    if case.kind == "correctness":
        return _required(case.expect_verdict).value
    return _grounding_label(
        _required(case.expect_faithful), _required(case.expect_citation_supported)
    )


def _grounding_label(faithful: bool, citation_supported: bool) -> str:
    return f"faithful={faithful} citation_supported={citation_supported}"


def _required[T](value: T | None) -> T:
    """A field the case's model validator guarantees for its kind."""
    if value is None:
        raise ValueError("calibration case is missing a field its kind requires")
    return value


def _rate(values: Iterable[bool | None]) -> float | None:
    applicable = [v for v in values if v is not None]
    return sum(applicable) / len(applicable) if applicable else None
