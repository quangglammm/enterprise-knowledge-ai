"""At-least-once in-memory queue with SQS-like leases, delays and redelivery."""

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass

from enterprise_knowledge.domain.ids import JobId
from enterprise_knowledge.domain.ports import QueueMessage


@dataclass(slots=True)
class _Message:
    job_id: JobId
    available_at: float
    deliveries: int = 0
    receipt: str | None = None


class InMemoryJobQueue:
    """A received message is invisible for ``visibility_seconds``, then receivable again."""

    def __init__(
        self,
        *,
        visibility_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._messages: list[_Message] = []
        self._visibility = visibility_seconds
        self._clock = clock
        self._receipts = itertools.count(1)
        self.enqueued: list[tuple[JobId, float]] = []  # (job, delay) of every enqueue

    async def enqueue(self, job_id: JobId, *, delay_seconds: float = 0.0) -> None:
        self.enqueued.append((job_id, delay_seconds))
        self._messages.append(_Message(job_id=job_id, available_at=self._clock() + delay_seconds))

    async def receive(self, *, max_messages: int, wait_seconds: float) -> list[QueueMessage]:
        now = self._clock()
        received: list[QueueMessage] = []
        for message in self._messages:
            if len(received) >= max_messages:
                break
            if message.available_at > now:
                continue
            message.deliveries += 1
            message.receipt = f"r{next(self._receipts)}"
            message.available_at = now + self._visibility
            received.append(
                QueueMessage(
                    job_id=message.job_id,
                    receipt=message.receipt,
                    delivery_count=message.deliveries,
                )
            )
        return received

    async def ack(self, message: QueueMessage) -> None:
        self._messages = [m for m in self._messages if m.receipt != message.receipt]

    @property
    def depth(self) -> int:
        return len(self._messages)
