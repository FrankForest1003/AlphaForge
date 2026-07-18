# HTTP API Draft

Status: contract draft; no FastAPI transport is implemented in Phase 1.

Base path: `/v1`. JSON media type: `application/json`. Strategy document media type: `application/vnd.alphaforge.strategy+json;version=0.1-draft`.

## POST /v1/optimisations

Creates an asynchronous optimisation job from a parent spec and exactly five normalised validation results.

- Request body: `OptimizationRequest`.
- Success: `202 Accepted` with `optimization_id`, `status="queued"` and status URL.
- Client must send `Idempotency-Key`; a replay with the same body returns the original job.
- `422`: schema or deterministic policy violation.
- `409`: same idempotency key used with a different body.

The service must reject Test-set evidence before enqueuing work.

## GET /v1/optimisations/{optimization_id}

Returns job state:

```text
queued → analysing → designing → validating → generating → backtesting → deciding → completed
                                                                                  ↘ failed
```

On completion, response body is `OptimizationResult`. Long-running engine work is never performed inside the request thread.

## POST /v1/backtests

Future Member C execution boundary. Accepts a validated Strategy Manifest and code artefact reference, returns `202` and a `run_id`. The Web UI must call the application service, not LEAN directly.

## GET /v1/backtests/{run_id}

Returns engine status and, on completion, a normalised `BacktestResult`. Raw LEAN artefacts are referenced by opaque IDs, not absolute local paths.

## Error envelope

```json
{
  "error": {
    "code": "TEST_EVIDENCE_FORBIDDEN",
    "message": "Held-out test evidence cannot be used during optimisation.",
    "request_id": "req_...",
    "details": [{"path": "/evidence/4/dataset_split", "reason": "must not be test"}]
  }
}
```

Messages are safe for users; provider logs, prompts, credentials and local paths are never returned.
