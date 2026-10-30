# Public API Rate Limits

This page describes the limits of the public shipment tracking API used by customers and partners.

## Limits per API key

Each API key may send up to 100 requests per minute. Short bursts of up to 200 requests are accepted as long as the average over one minute stays within the limit. Bulk tracking requests count as one request per 50 tracking numbers.

## When a limit is exceeded

Requests over the limit are rejected with HTTP status 429 and a Retry-After header that states how many seconds the client should wait. Clients must wait at least that long before retrying.

## Higher limits

Partners who need higher limits contact their account manager. Higher limits are granted for 12 months and reviewed at renewal.
