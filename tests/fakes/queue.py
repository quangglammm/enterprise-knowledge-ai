"""At-least-once in-memory queue. Unacked messages can be redelivered, like SQS."""

import itertools
from collections import deque

from enterprise_knowledge.domain.ids import JobId
from enterprise_knowledge.domain.ports import QueueMessage


class InMemoryJobQueue:
    def __init__(self) -> None:
        self._ready: deque[tuple[JobId, int]] = deque()
        self._in_flight: dict[str, tuple[JobId, int]] = {}
        self._receipts = itertools.count(1)

    async def enqueue(self, job_id: JobId) -> None:
        self._ready.append((job_id, 0))

    async def receive(self, *, max_messages: int, wait_seconds: float) -> list[QueueMessage]:
        messages: list[QueueMessage] = []
        while self._ready and len(messages) < max_messages:
            job_id, deliveries = self._ready.popleft()
            receipt = f"r{next(self._receipts)}"
            self._in_flight[receipt] = (job_id, deliveries + 1)
            messages.append(
                QueueMessage(job_id=job_id, receipt=receipt, delivery_count=deliveries + 1)
            )
        return messages

    async def ack(self, message: QueueMessage) -> None:
        self._in_flight.pop(message.receipt, None)

    def expire_in_flight(self) -> None:
        """Simulate a visibility timeout: unacked messages become receivable again."""
        self._ready.extend(self._in_flight.values())
        self._in_flight.clear()

    @property
    def depth(self) -> int:
        return len(self._ready) + len(self._in_flight)
