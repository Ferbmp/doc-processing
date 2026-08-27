from datetime import timedelta

import pytest
from django.utils import timezone

from documents.models import AuditEvent, ExtractionResult, ProcessingJob
from documents.services import processing
from documents.services.processing import (
    OUTCOME_COMPLETED,
    OUTCOME_FAILED,
    OUTCOME_IGNORED,
    OUTCOME_RETRY_SCHEDULED,
    OUTCOME_REVIEW_REQUIRED,
    execute_job,
    recover_stale_jobs,
)
from documents.services.queue import claim_next_job, compute_backoff
from documents.states import DocumentStatus, EventType, JobStatus

pytestmark = pytest.mark.django_db


def event_types(document):
    return list(
        AuditEvent.objects.filter(document=document)
        .order_by("created_at", "id")
        .values_list("event_type", flat=True)
    )


# --- happy path -------------------------------------------------------------


def test_clean_extraction_is_accepted_automatically(make_document, drain):
    document = make_document("success")

    assert drain() == [OUTCOME_COMPLETED]

    document.refresh_from_db()
    assert document.status == DocumentStatus.COMPLETED
    result = ExtractionResult.objects.get(document=document)
    assert result.needs_review is False
    assert result.review_reasons == []
    assert result.total == result.subtotal + result.tax
    assert event_types(document) == [
        EventType.DOCUMENT_RECEIVED,
        EventType.JOB_ENQUEUED,
        EventType.PROCESSING_STARTED,
        EventType.EXTRACTION_SUCCEEDED,
        EventType.RESULT_ACCEPTED,
    ]


# --- review paths -----------------------------------------------------------


def test_low_confidence_goes_to_review(make_document, drain):
    document = make_document("low_confidence")

    assert drain() == [OUTCOME_REVIEW_REQUIRED]

    document.refresh_from_db()
    assert document.status == DocumentStatus.REVIEW_REQUIRED
    result = document.result
    assert result.needs_review is True
    assert any("confidence" in reason for reason in result.review_reasons)


def test_incomplete_extraction_goes_to_review(make_document, drain):
    document = make_document("incomplete")

    assert drain() == [OUTCOME_REVIEW_REQUIRED]

    document.refresh_from_db()
    assert document.status == DocumentStatus.REVIEW_REQUIRED
    assert any("missing" in reason for reason in document.result.review_reasons)


def test_impossible_arithmetic_is_never_stored(make_document, drain):
    document = make_document("arithmetic_mismatch")

    assert drain() == [OUTCOME_REVIEW_REQUIRED]

    result = ExtractionResult.objects.get(document=document)
    # The figure the service claimed is preserved for audit, but it is not
    # allowed into the financial columns.
    assert result.total is None
    assert result.raw_extraction["fields"]["total"] is not None
    assert any("does not equal subtotal + tax" in r for r in result.review_reasons)


def test_duplicate_invoice_number_is_held_for_review(make_document, drain):
    first = make_document("success", invoice_number="DUP-1")
    second = make_document("success", invoice_number="DUP-1", note="resubmitted scan")

    outcomes = drain()

    assert outcomes == [OUTCOME_COMPLETED, OUTCOME_REVIEW_REQUIRED]
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == DocumentStatus.COMPLETED
    assert second.status == DocumentStatus.REVIEW_REQUIRED
    assert any("already" in reason for reason in second.result.review_reasons)
    # Exactly one accepted record exists for that invoice.
    assert (
        ExtractionResult.objects.filter(invoice_number="DUP-1", needs_review=False).count() == 1
    )


# --- retries ----------------------------------------------------------------


def test_transient_failure_is_retried_then_succeeds(make_document, drain):
    document = make_document("flaky")

    assert drain() == [OUTCOME_RETRY_SCHEDULED, OUTCOME_COMPLETED]

    document.refresh_from_db()
    assert document.status == DocumentStatus.COMPLETED
    assert document.attempts == 2
    assert event_types(document) == [
        EventType.DOCUMENT_RECEIVED,
        EventType.JOB_ENQUEUED,
        EventType.PROCESSING_STARTED,
        EventType.ATTEMPT_FAILED,
        EventType.RETRY_SCHEDULED,
        EventType.JOB_ENQUEUED,
        EventType.PROCESSING_STARTED,
        EventType.EXTRACTION_SUCCEEDED,
        EventType.RESULT_ACCEPTED,
    ]
    # One row per attempt, so the attempt history survives.
    assert ProcessingJob.objects.filter(document=document).count() == 2


def test_retries_are_exhausted_then_the_document_fails(make_document, drain):
    document = make_document("transient_failure")

    outcomes = drain()

    assert outcomes == [
        OUTCOME_RETRY_SCHEDULED,
        OUTCOME_RETRY_SCHEDULED,
        OUTCOME_FAILED,
    ]
    document.refresh_from_db()
    assert document.status == DocumentStatus.FAILED
    assert document.attempts == 3
    assert ProcessingJob.objects.filter(document=document, status=JobStatus.FAILED).count() == 3
    assert not ExtractionResult.objects.filter(document=document).exists()


def test_permanent_failure_is_not_retried(make_document, drain):
    document = make_document("permanent_failure")

    assert drain() == [OUTCOME_FAILED]

    document.refresh_from_db()
    assert document.status == DocumentStatus.FAILED
    assert document.attempts == 1
    assert ProcessingJob.objects.filter(document=document).count() == 1
    failure = AuditEvent.objects.get(document=document, event_type=EventType.PROCESSING_FAILED)
    assert failure.context["retryable"] is False


def test_backoff_grows_and_is_capped(settings):
    settings.PROCESSING = {
        **settings.PROCESSING,
        "RETRY_BASE_SECONDS": 2.0,
        "RETRY_MAX_SECONDS": 10.0,
        "RETRY_JITTER_SECONDS": 0.0,
    }

    delays = [compute_backoff(attempt).total_seconds() for attempt in (1, 2, 3, 4, 5)]

    assert delays == [2.0, 4.0, 8.0, 10.0, 10.0]


# --- idempotency and crash safety -------------------------------------------


def test_re_executing_a_finished_job_changes_nothing(make_document, drain):
    document = make_document("success")
    drain()
    job = ProcessingJob.objects.get(document=document)
    original = ExtractionResult.objects.get(document=document)

    outcome = execute_job(job, worker_id="second-worker", sleep=False)

    assert outcome == OUTCOME_IGNORED
    assert ExtractionResult.objects.filter(document=document).count() == 1
    reloaded = ExtractionResult.objects.get(document=document)
    assert (reloaded.total, reloaded.extracted_at) == (original.total, original.extracted_at)
    document.refresh_from_db()
    assert document.status == DocumentStatus.COMPLETED
    assert AuditEvent.objects.filter(
        document=document, event_type=EventType.DUPLICATE_EXECUTION_IGNORED
    ).exists()


def test_redelivered_job_cannot_overwrite_a_decided_document(make_document, drain):
    """The nastier version: the job is still RUNNING when it is executed again."""

    document = make_document("success")
    drain()
    ProcessingJob.objects.filter(document=document).update(
        status=JobStatus.RUNNING, locked_by="zombie-worker", locked_at=timezone.now()
    )
    job = ProcessingJob.objects.get(document=document)

    assert execute_job(job, worker_id="zombie-worker", sleep=False) == OUTCOME_IGNORED
    assert ExtractionResult.objects.filter(document=document).count() == 1


def test_a_crash_mid_write_leaves_no_partial_record(monkeypatch, make_document):
    document = make_document("success")
    job = claim_next_job("w1")
    assert job is not None

    def boom(*args, **kwargs):
        raise RuntimeError("database went away halfway through")

    monkeypatch.setattr(processing, "_upsert_result", boom)

    with pytest.raises(RuntimeError):
        execute_job(job, worker_id="w1", sleep=False)

    assert not ExtractionResult.objects.filter(document=document).exists()
    document.refresh_from_db()
    # Still PROCESSING with the job still RUNNING, which is precisely what the
    # stale job reaper is for. Nothing partial was committed.
    assert document.status == DocumentStatus.PROCESSING
    assert not AuditEvent.objects.filter(
        document=document, event_type=EventType.EXTRACTION_SUCCEEDED
    ).exists()


def test_stale_job_from_a_dead_worker_is_requeued(make_document):
    document = make_document("success")
    job = claim_next_job("worker-that-dies")
    assert job is not None
    ProcessingJob.objects.filter(pk=job.pk).update(
        locked_at=timezone.now() - timedelta(minutes=10)
    )

    assert recover_stale_jobs(worker_id="reaper") == 1

    document.refresh_from_db()
    assert document.status == DocumentStatus.RETRY_SCHEDULED
    job.refresh_from_db()
    assert (job.status, job.error_type) == (JobStatus.FAILED, "worker_lost")
    replacement = ProcessingJob.objects.get(document=document, status=JobStatus.QUEUED)
    assert replacement.attempt == 2
    assert AuditEvent.objects.filter(
        document=document, event_type=EventType.JOB_RECOVERED
    ).exists()


def test_recovering_a_job_for_an_already_decided_document_does_not_reprocess(
    make_document, drain
):
    document = make_document("success")
    drain()
    ProcessingJob.objects.filter(document=document).update(
        status=JobStatus.RUNNING, locked_at=timezone.now() - timedelta(minutes=10)
    )

    assert recover_stale_jobs(worker_id="reaper") == 1

    document.refresh_from_db()
    assert document.status == DocumentStatus.COMPLETED
    assert not ProcessingJob.objects.filter(
        document=document, status=JobStatus.QUEUED
    ).exists()
