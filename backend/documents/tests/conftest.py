import json

import pytest

from documents.services.processing import execute_job
from documents.services.queue import claim_next_job
from documents.services.submission import submit_document


@pytest.fixture(autouse=True)
def fast_pipeline(settings):
    """No simulated latency and no retry backoff, so tests run in milliseconds."""

    settings.PROCESSING = {
        **settings.PROCESSING,
        "MAX_ATTEMPTS": 3,
        "RETRY_BASE_SECONDS": 0.0,
        "RETRY_MAX_SECONDS": 0.0,
        "RETRY_JITTER_SECONDS": 0.0,
        "STALE_JOB_TIMEOUT_SECONDS": 60,
        "REVIEW_CONFIDENCE_THRESHOLD": 0.85,
    }
    settings.AI_SIMULATOR = {**settings.AI_SIMULATOR, "LATENCY_MS": 0}
    return settings


def invoice_json(**overrides) -> str:
    payload = {
        "vendor_name": "Northwind Supplies Ltd",
        "invoice_number": "INV-9001",
        "invoice_date": "2026-08-14",
        "currency": "GBP",
        "subtotal": "1000.00",
        "tax": "200.00",
        "total": "1200.00",
    }
    payload.update(overrides)
    return json.dumps(payload)


@pytest.fixture
def make_document():
    def _make(outcome: str = "success", **overrides):
        document, _ = submit_document(
            content=invoice_json(**overrides),
            source_reference="pytest",
            forced_outcome=outcome,
        )
        return document

    return _make


@pytest.fixture
def drain():
    """Claim and execute every job that is currently due."""

    def _drain(worker_id: str = "test-worker", limit: int = 20) -> list[str]:
        outcomes = []
        for _ in range(limit):
            job = claim_next_job(worker_id)
            if job is None:
                break
            outcomes.append(execute_job(job, worker_id=worker_id, sleep=False))
        return outcomes

    return _drain
