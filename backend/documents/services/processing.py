"""Executing one extraction attempt, safely.

The shape of ``execute_job`` is deliberate:

1. A cheap, unlocked pre-check skips work for documents that are already
   decided (avoids a pointless call to the extraction service).
2. The extraction service is called *outside* any transaction. A slow third
   party must never hold row locks on financial records.
3. All writes happen in a single transaction that starts by re-reading the job
   and the document ``FOR UPDATE``. That locked re-read is the authoritative
   idempotency gate: if another worker already decided this document, this
   attempt records that it was ignored and changes nothing.

The result of an attempt is therefore all-or-nothing. There is no window in
which a financial record exists without the matching document status and audit
entry.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..ai.simulator import (
    ExtractionError,
    ExtractionResponse,
    TransientExtractionError,
    extract_invoice,
)
from ..models import Document, ExtractionResult, ProcessingJob
from ..states import DECIDED_STATUSES, DocumentStatus, EventType, JobStatus
from .queue import compute_backoff, enqueue_job
from .state import record_event, transition
from .validation import NormalizedResult, normalize_extraction

logger = logging.getLogger(__name__)

# Outcome labels returned by execute_job, for logging and tests.
OUTCOME_COMPLETED = "completed"
OUTCOME_REVIEW_REQUIRED = "review_required"
OUTCOME_RETRY_SCHEDULED = "retry_scheduled"
OUTCOME_FAILED = "failed"
OUTCOME_IGNORED = "ignored"


def execute_job(job: ProcessingJob, *, worker_id: str = "", sleep: bool = True) -> str:
    worker_id = worker_id or job.locked_by or "worker"
    document = Document.objects.get(pk=job.document_id)

    if document.status in DECIDED_STATUSES:
        return _ignore_duplicate_execution(job, document, worker_id)

    try:
        response = extract_invoice(
            raw_text=document.raw_text,
            raw_payload=document.raw_payload,
            seed=document.content_hash,
            attempt=job.attempt,
            forced_outcome=document.forced_outcome,
            sleep=sleep,
        )
    except ExtractionError as exc:
        return handle_attempt_error(job, exc, worker_id=worker_id)

    normalized = normalize_extraction(response)
    return _persist_attempt_result(job, response, normalized, worker_id=worker_id)


# --- success path ------------------------------------------------------------


def _persist_attempt_result(
    job: ProcessingJob,
    response: ExtractionResponse,
    normalized: NormalizedResult,
    *,
    worker_id: str,
) -> str:
    with transaction.atomic():
        locked = _lock_job_and_document(job)
        if locked is None:
            return _ignore_duplicate_execution(
                job, Document.objects.get(pk=job.document_id), worker_id
            )
        fresh_job, document = locked

        reasons = list(normalized.review_reasons)
        reasons.extend(_duplicate_invoice_reasons(document, normalized))
        needs_review = bool(reasons)

        record_event(
            document=document,
            job=fresh_job,
            event_type=EventType.EXTRACTION_SUCCEEDED,
            message=(
                f"Extraction completed with confidence {response.confidence:.2f} "
                f"(simulated outcome: {response.outcome})"
            ),
            actor=worker_id,
            context={
                "outcome": response.outcome,
                "confidence": response.confidence,
                "extraction_id": response.extraction_id,
                "latency_ms": response.latency_ms,
            },
        )

        try:
            # Savepoint: the unique-accepted-invoice index can still fire if
            # two documents for the same invoice complete concurrently.
            with transaction.atomic():
                _upsert_result(document, fresh_job, response, normalized, reasons, needs_review)
        except IntegrityError:
            reasons.append(
                "database rejected this as a duplicate of an already accepted invoice"
            )
            _upsert_result(document, fresh_job, response, normalized, reasons, needs_review=True)
            needs_review = True

        _finish_job(fresh_job, JobStatus.SUCCEEDED)

        if needs_review:
            transition(
                document=document,
                to_status=DocumentStatus.REVIEW_REQUIRED,
                event_type=EventType.REVIEW_REQUIRED,
                message="Result requires review: " + "; ".join(reasons),
                job=fresh_job,
                actor=worker_id,
                context={"reasons": reasons},
            )
            return OUTCOME_REVIEW_REQUIRED

        transition(
            document=document,
            to_status=DocumentStatus.COMPLETED,
            event_type=EventType.RESULT_ACCEPTED,
            message=(
                f"Result accepted automatically: {normalized.currency} {normalized.total} "
                f"from {normalized.vendor_name} ({normalized.invoice_number})"
            ),
            job=fresh_job,
            actor=worker_id,
        )
        return OUTCOME_COMPLETED


def _upsert_result(
    document: Document,
    job: ProcessingJob,
    response: ExtractionResponse,
    normalized: NormalizedResult,
    reasons: list[str],
    needs_review: bool,
) -> ExtractionResult:
    """Write the financial record for this document.

    ``update_or_create`` on a one-to-one primary key: a repeated execution can
    only overwrite this document's single record, never create a second one.
    """

    defaults: dict[str, Any] = {
        "attempt": job.attempt,
        "vendor_name": normalized.vendor_name,
        "invoice_number": normalized.invoice_number,
        "invoice_date": normalized.invoice_date,
        "currency": normalized.currency,
        "subtotal": normalized.subtotal,
        "tax": normalized.tax,
        "total": normalized.total,
        "line_items": normalized.line_items,
        "confidence": normalized.confidence,
        "needs_review": needs_review,
        "review_reasons": reasons,
        "raw_extraction": response.as_raw(),
        "extracted_at": timezone.now(),
    }
    result, _ = ExtractionResult.objects.update_or_create(document=document, defaults=defaults)
    return result


def _duplicate_invoice_reasons(document: Document, normalized: NormalizedResult) -> list[str]:
    if not normalized.vendor_name or not normalized.invoice_number:
        return []
    clash = (
        ExtractionResult.objects.filter(
            vendor_name=normalized.vendor_name,
            invoice_number=normalized.invoice_number,
            needs_review=False,
        )
        .exclude(document_id=document.id)
        .first()
    )
    if clash is None:
        return []
    return [
        f"invoice {normalized.invoice_number} from {normalized.vendor_name} was already "
        f"accepted on document {clash.document_id}"
    ]


# --- failure path -----------------------------------------------------------


def handle_attempt_error(
    job: ProcessingJob,
    exc: Exception,
    *,
    worker_id: str,
) -> str:
    """Record a failed attempt and either schedule a retry or give up."""

    retryable = bool(getattr(exc, "retryable", False))
    code = getattr(exc, "code", exc.__class__.__name__)

    with transaction.atomic():
        locked = _lock_job_and_document(job)
        if locked is None:
            return _ignore_duplicate_execution(
                job, Document.objects.get(pk=job.document_id), worker_id
            )
        fresh_job, document = locked

        _finish_job(fresh_job, JobStatus.FAILED, error_type=code, error_message=str(exc))
        record_event(
            document=document,
            job=fresh_job,
            event_type=EventType.ATTEMPT_FAILED,
            message=f"Attempt {fresh_job.attempt} failed: {exc}",
            actor=worker_id,
            context={"error_type": code, "retryable": retryable},
        )
        return _schedule_retry_or_give_up(
            document,
            fresh_job,
            retryable=retryable,
            reason=str(exc),
            error_type=code,
            worker_id=worker_id,
        )


def _schedule_retry_or_give_up(
    document: Document,
    job: ProcessingJob,
    *,
    retryable: bool,
    reason: str,
    error_type: str,
    worker_id: str,
) -> str:
    if retryable and job.has_attempts_left:
        delay = compute_backoff(job.attempt)
        next_attempt = job.attempt + 1
        transition(
            document=document,
            to_status=DocumentStatus.RETRY_SCHEDULED,
            event_type=EventType.RETRY_SCHEDULED,
            message=(
                f"Processing retried: attempt {next_attempt} of {job.max_attempts} "
                f"scheduled in {delay.total_seconds():.1f}s"
            ),
            job=job,
            actor=worker_id,
            context={"next_attempt": next_attempt, "delay_seconds": delay.total_seconds()},
        )
        enqueue_job(
            document,
            attempt=next_attempt,
            delay=delay,
            actor=worker_id,
            message=f"Attempt {next_attempt} queued after a retryable failure",
        )
        return OUTCOME_RETRY_SCHEDULED

    if retryable:
        message = (
            f"Processing failed permanently after {job.attempt} of {job.max_attempts} "
            f"attempts: {reason}"
        )
    else:
        message = f"Processing failed with a non-retryable error: {reason}"

    transition(
        document=document,
        to_status=DocumentStatus.FAILED,
        event_type=EventType.PROCESSING_FAILED,
        message=message,
        job=job,
        actor=worker_id,
        context={"error_type": error_type, "retryable": retryable, "attempts": job.attempt},
    )
    return OUTCOME_FAILED


def fail_job_with_unexpected_error(job: ProcessingJob, exc: Exception, *, worker_id: str) -> str:
    """Last resort for bugs: treat an unexpected exception as retryable.

    If even this fails, the job stays RUNNING and the stale job reaper picks it
    up, so no document can get stuck silently.
    """

    wrapped = TransientExtractionError(
        f"unexpected worker error: {exc.__class__.__name__}: {exc}", code="unexpected_error"
    )
    return handle_attempt_error(job, wrapped, worker_id=worker_id)


# --- crash recovery ---------------------------------------------------------


def recover_stale_jobs(*, worker_id: str = "reaper", limit: int = 50) -> int:
    """Requeue work abandoned by workers that died mid-attempt.

    A worker that is SIGKILLed leaves its job RUNNING forever. Anything holding
    a lock older than STALE_JOB_TIMEOUT_SECONDS is assumed dead. This is the
    price of at-least-once delivery: a job may be executed twice, which is why
    ``_persist_attempt_result`` re-checks state under a row lock.
    """

    cutoff = timezone.now() - timedelta(
        seconds=int(settings.PROCESSING["STALE_JOB_TIMEOUT_SECONDS"])
    )
    candidate_ids = list(
        ProcessingJob.objects.filter(status=JobStatus.RUNNING, locked_at__lt=cutoff)
        .order_by("locked_at")
        .values_list("pk", flat=True)[:limit]
    )

    recovered = 0
    for job_id in candidate_ids:
        with transaction.atomic():
            job = (
                ProcessingJob.objects.select_for_update(skip_locked=True)
                .filter(pk=job_id, status=JobStatus.RUNNING, locked_at__lt=cutoff)
                .first()
            )
            if job is None:
                continue
            document = Document.objects.select_for_update().get(pk=job.document_id)

            stale_for = (timezone.now() - job.locked_at).total_seconds()
            if document.status in DECIDED_STATUSES:
                # The original worker finished the document but died before it
                # could close the job row out.
                _finish_job(job, JobStatus.SUCCEEDED)
                record_event(
                    document=document,
                    job=job,
                    event_type=EventType.JOB_RECOVERED,
                    message=(
                        f"Closed job abandoned by {job.locked_by or 'unknown worker'}; "
                        f"document was already {document.status}"
                    ),
                    actor=worker_id,
                    context={"stale_for_seconds": round(stale_for, 1)},
                )
                recovered += 1
                continue

            _finish_job(
                job,
                JobStatus.FAILED,
                error_type="worker_lost",
                error_message=f"lock held by {job.locked_by or 'unknown'} went stale",
            )
            record_event(
                document=document,
                job=job,
                event_type=EventType.JOB_RECOVERED,
                message=(
                    f"Attempt {job.attempt} was abandoned by "
                    f"{job.locked_by or 'an unknown worker'} after {stale_for:.0f}s"
                ),
                actor=worker_id,
                context={"stale_for_seconds": round(stale_for, 1)},
            )
            if document.status == DocumentStatus.PROCESSING:
                _schedule_retry_or_give_up(
                    document,
                    job,
                    retryable=True,
                    reason="worker stopped responding mid-attempt",
                    error_type="worker_lost",
                    worker_id=worker_id,
                )
            recovered += 1

    return recovered


# --- shared helpers ---------------------------------------------------------


def _lock_job_and_document(job: ProcessingJob) -> tuple[ProcessingJob, Document] | None:
    """Re-read job and document ``FOR UPDATE`` and verify this attempt still owns them.

    Lock order is always job then document, in every code path, so concurrent
    workers cannot deadlock.
    """

    fresh_job = ProcessingJob.objects.select_for_update().get(pk=job.pk)
    document = Document.objects.select_for_update().get(pk=job.document_id)

    if fresh_job.status != JobStatus.RUNNING or document.status != DocumentStatus.PROCESSING:
        return None
    return fresh_job, document


def _ignore_duplicate_execution(job: ProcessingJob, document: Document, worker_id: str) -> str:
    """Record that an attempt did nothing because the work was already done."""

    with transaction.atomic():
        fresh_job = ProcessingJob.objects.select_for_update().get(pk=job.pk)
        if fresh_job.status in (JobStatus.QUEUED, JobStatus.RUNNING):
            _finish_job(fresh_job, JobStatus.SUCCEEDED)
        record_event(
            document=document,
            job=fresh_job,
            event_type=EventType.DUPLICATE_EXECUTION_IGNORED,
            message=(
                f"Attempt {fresh_job.attempt} discarded: document is already "
                f"{document.status} and its record must not be overwritten"
            ),
            actor=worker_id,
            context={"document_status": document.status},
        )
    logger.info("doc=%s job=%s duplicate execution ignored", document.id, job.pk)
    return OUTCOME_IGNORED


def _finish_job(
    job: ProcessingJob,
    status: str,
    *,
    error_type: str = "",
    error_message: str = "",
) -> None:
    job.status = status
    job.finished_at = timezone.now()
    job.error_type = error_type
    job.error_message = error_message
    job.save(
        update_fields=["status", "finished_at", "error_type", "error_message", "updated_at"]
    )
