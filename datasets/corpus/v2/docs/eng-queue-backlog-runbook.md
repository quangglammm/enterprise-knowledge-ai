# Job Queue Backlog Runbook

## Symptoms

The ingestion job queue alarm fires when more than 10,000 messages have been waiting for longer than 10 minutes. Users notice that uploaded documents stay in the pending state and search results do not include new files.

## Escalation

The primary on-call engineer owns the response. If the backlog keeps growing after the first scaling step, the engineer involves the platform team in the incident channel.

## Steps

1. Check the worker dashboard for failing jobs. A sudden rise in failures usually means a downstream dependency is unavailable, and scaling will not help.
2. If workers are healthy but saturated, scale the worker service up to a maximum of 20 tasks. Do not exceed 20 tasks, because the database connection pool is sized for that limit.
3. Watch the queue depth for 15 minutes. It should fall steadily once the extra workers are running.

## Dead-letter queue

Messages that fail 5 times are moved to the dead-letter queue, where they are kept for 14 days. After the root cause is fixed, redrive the dead-letter messages in batches of at most 500 and confirm that the failure count stays at zero.

## Rollback

Scale the worker service back to its normal size of 4 tasks within 1 hour after the queue depth falls below 1,000 messages.
