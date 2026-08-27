"""Tests that need real committed transactions and more than one connection."""

from threading import Thread

import pytest
from django.db import connection

from documents.models import Document, ExtractionResult, ProcessingJob
from documents.services import processing
from documents.services.processing import (
    OUTCOME_COMPLETED,
    OUTCOME_REVIEW_REQUIRED,
    execute_job,
)
from documents.services.queue import claim_next_job
from documents.services.submission import submit_document
from documents.states import DocumentStatus
from documents.tests.conftest import invoice_json


def run_in_threads(target, count: int) -> list:
    collected: list = []

    def wrapper(index: int) -> None:
        try:
            collected.append(target(index))
        finally:
            # Each thread gets its own connection; hand it back explicitly.
            connection.close()

    threads = [Thread(target=wrapper, args=(i,)) for i in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
    return collected


@pytest.mark.django_db(transaction=True)
def test_only_one_worker_can_claim_a_single_job(make_document):
    make_document("success")

    claimed = run_in_threads(lambda i: claim_next_job(f"worker-{i}"), 4)

    winners = [job for job in claimed if job is not None]
    assert len(winners) == 1, "SKIP LOCKED must hand a job to exactly one worker"
    assert ProcessingJob.objects.filter(locked_by__startswith="worker-").count() == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_workers_take_different_jobs(make_document):
    make_document("success", invoice_number="A-1")
    make_document("success", invoice_number="A-2")

    claimed = run_in_threads(lambda i: claim_next_job(f"worker-{i}"), 2)

    job_ids = {job.pk for job in claimed if job is not None}
    assert len(job_ids) == 2
    assert Document.objects.filter(status=DocumentStatus.PROCESSING).count() == 2


@pytest.mark.django_db(transaction=True)
def test_concurrent_identical_submissions_create_one_document():
    content = invoice_json()

    results = run_in_threads(lambda _i: submit_document(content=content)[1], 4)

    assert results.count(True) == 1, "exactly one caller should be told it created the document"
    assert Document.objects.count() == 1
    assert ProcessingJob.objects.count() == 1


@pytest.mark.django_db
def test_database_has_the_final_say_on_duplicate_invoices(monkeypatch, make_document, drain):
    """If the application-level duplicate check loses a race, the index still wins.

    Simulated by blinding the pre-check, which is exactly what a concurrent
    completion would do: both attempts look, both see nothing, one insert has
    to lose.
    """

    make_document("success", invoice_number="RACE-1")
    drain()

    second = make_document("success", invoice_number="RACE-1", note="second copy")
    monkeypatch.setattr(processing, "_duplicate_invoice_reasons", lambda *a, **k: [])

    job = claim_next_job("worker-b")
    assert execute_job(job, worker_id="worker-b", sleep=False) == OUTCOME_REVIEW_REQUIRED

    second.refresh_from_db()
    assert second.status == DocumentStatus.REVIEW_REQUIRED
    assert any("duplicate" in reason for reason in second.result.review_reasons)
    assert (
        ExtractionResult.objects.filter(invoice_number="RACE-1", needs_review=False).count() == 1
    )


@pytest.mark.django_db(transaction=True)
def test_concurrent_acceptances_of_same_invoice_leave_one_accepted(monkeypatch, make_document):
    """Two workers finish the same vendor+invoice at once; the unique index keeps one.

    The app-level duplicate check is blinded so both threads pass the TOCTOU
    window the way a real race would: both look, both see nothing accepted yet,
    then both try to write ``needs_review=False``. Exactly one insert survives.
    """

    monkeypatch.setattr(processing, "_duplicate_invoice_reasons", lambda *a, **k: [])

    first = make_document("success", invoice_number="CONCUR-1", note="scan-a")
    second = make_document("success", invoice_number="CONCUR-1", note="scan-b")

    job_a = claim_next_job("worker-a")
    job_b = claim_next_job("worker-b")
    assert job_a is not None and job_b is not None
    assert {job_a.document_id, job_b.document_id} == {first.id, second.id}

    jobs = [job_a, job_b]
    outcomes = run_in_threads(
        lambda i: execute_job(jobs[i], worker_id=f"worker-{i}", sleep=False),
        2,
    )

    assert set(outcomes) == {OUTCOME_COMPLETED, OUTCOME_REVIEW_REQUIRED}
    assert (
        ExtractionResult.objects.filter(
            invoice_number="CONCUR-1", needs_review=False
        ).count()
        == 1
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert {first.status, second.status} == {
        DocumentStatus.COMPLETED,
        DocumentStatus.REVIEW_REQUIRED,
    }

    loser = first if first.status == DocumentStatus.REVIEW_REQUIRED else second
    assert any("duplicate" in reason for reason in loser.result.review_reasons)
