"""Typed workflow failures. Like generation errors, they are never abstentions."""

from typing import ClassVar

from enterprise_knowledge.domain.errors import DomainError


class WorkflowError(DomainError):
    category: ClassVar[str] = "workflow_error"


class InvalidWorkflowTransitionError(WorkflowError):
    """The workflow tried a transition its state machine does not allow (a code bug)."""

    category: ClassVar[str] = "invalid_workflow_transition"


class WorkflowLimitError(WorkflowError):
    """A step or model-call limit would be exceeded."""

    category: ClassVar[str] = "workflow_limit_exceeded"


class WorkflowTimeoutError(WorkflowError):
    """The workflow's wall-clock deadline passed before it could finish."""

    category: ClassVar[str] = "workflow_timeout"
