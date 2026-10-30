"""Parse a model reply into a validated AnswerResponse (ADR-0009).

The model cites evidence by label (E1, E2, ...). Labels map back to chunk IDs here, so
an answer can only cite chunks that were in its prompt; anything else is rejected.
"""

import re
from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from enterprise_knowledge.domain.answers import AnswerResponse, AnswerStatus, Citation
from enterprise_knowledge.domain.ids import ChunkId
from enterprise_knowledge.generation.errors import (
    InvalidModelOutputError,
    UnresolvedCitationError,
)

DEFAULT_ABSTENTION_REASON = "insufficient_evidence"
MAX_ABSTENTION_REASON_CHARS = 200
# Open-weight models often wrap JSON in a Markdown fence despite instructions.
_FENCE = re.compile(r"^```(?:json)?\s*(?P<body>.*?)\s*```$", re.DOTALL | re.IGNORECASE)
_INLINE_MARKER = re.compile(r"\[(E\d+)\]")


class _ModelAnswer(BaseModel):
    """The JSON object the prompt asks for. Unknown extra keys are ignored."""

    model_config = ConfigDict(frozen=True)

    status: AnswerStatus
    answer: str | None = None
    citations: list[str] = Field(default_factory=list)
    abstention_reason: str | None = None


def clean_json_reply(content: str) -> str:
    """Strip a Markdown fence, drop text after the first complete JSON value, and close
    objects or arrays left open at the end.

    Open-weight models often fence their JSON, sometimes drop the final ``}`` and sometimes
    append a note after it (all seen from Llama-3.3-70B in calibration). Only closing
    brackets are added, never content: a reply that ends inside a string is returned as is
    and fails validation.
    """
    body = content.strip()
    fenced = _FENCE.match(body)
    if fenced:
        body = fenced.group("body")
    closers = {"{": "}", "[": "]"}
    stack: list[str] = []
    in_string = escaped = False
    for index, char in enumerate(body):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char in closers:
            stack.append(closers[char])
        elif char in "}]" and stack and stack[-1] == char:
            stack.pop()
            if not stack:  # the first complete value ends here; ignore any trailing note
                return body[: index + 1]
    if in_string or not stack:
        return body
    return body + "".join(reversed(stack))


def parse_answer(content: str, labels: Mapping[str, ChunkId]) -> AnswerResponse:
    body = clean_json_reply(content)
    try:
        output = _ModelAnswer.model_validate_json(body)
    except ValidationError as exc:
        raise InvalidModelOutputError(_describe(exc)) from None

    if output.status is AnswerStatus.INSUFFICIENT_EVIDENCE:
        reason = (output.abstention_reason or "").strip()[:MAX_ABSTENTION_REASON_CHARS]
        return AnswerResponse.abstain(reason=reason or DEFAULT_ABSTENTION_REASON)

    inline = _INLINE_MARKER.findall(output.answer or "")
    cited = list(dict.fromkeys([*output.citations, *inline]))
    unknown = [label for label in cited if label not in labels]
    if unknown:
        raise UnresolvedCitationError(unknown)
    try:
        return AnswerResponse(
            status=AnswerStatus.ANSWERED,
            answer=output.answer,
            citations=tuple(Citation(chunk_id=labels[label]) for label in cited),
        )
    except ValidationError:
        raise InvalidModelOutputError(
            "an answered reply needs non-blank answer text and at least one citation"
        ) from None


def _describe(exc: ValidationError) -> str:
    """A short, model-facing description of the first problem. Never logged with input."""
    error = exc.errors(include_input=False, include_url=False)[0]
    location = ".".join(str(part) for part in error["loc"]) or "reply"
    return f"{location}: {error['msg']}"
