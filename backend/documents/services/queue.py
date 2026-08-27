"""A job queue that lives in Postgres.

Why not Celery: the interesting failure modes in this exercise are all about
the database (enqueue in the same transaction as the document, claim exactly
once across N workers, recover work abandoned by a dead worker). Postgres
gives us all three with ``SELECT ... FOR UPDATE SKIP LOCKED``, and the queue
state becomes part of the audit trail for free. See the README for what would
change in production.
"""

from __future__ import annotations

import logging
import random
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import Document, ProcessingJob
from ..states import DocumentStatus, EventType, JobStatus
from .state import record_event, transition

logger = logging.getLogger(__name__)


def compute_backoff(attempt: int) -> timedelta:
    """Exponential backoff with jitter, capped.

    Jitter matters even here: without it, a batch of documents that failed
    together would retry in lockstep and hammer the extraction service at the
    same instant.
    """

    config = settings.PROCESSING
    base = float(config["RETRY_BASE_SECONDS"])
    ceiling = float(config["RETRY_MAX_SECONDS"])
    jitter = float(config["RETRY_JITTER_SECONDS"])

    delay = min(base * (2 ** max(0, attempt - 1)), ceiling)
    return timedelta(seconds=delay + random.uniform(0, jitter))


def enqueue_job(
    document: Document,
    *,
    attempt: int = 1,
    delay: timedelta | None = None,
    actor: str = "",
    message: str | None = None,
) -> ProcessingJob | None:
    """Create the next job for a document, or return None if one already exists.

    The ``unique_live_job_per_document`` partial index is the real guard here:
    even if two callers race, only one QUEUED/RUNNING job can exist, so a
    document can never be processed twice concurrently.
    """

    run_after = timezone.now() + (delay or timedelta())
    try:
        # Savepoint, so a losing race does not poison the caller's transaction.
        with transaction.atomic():
            job = ProcessingJob.objects.create(
                document=document,
                attempt=attempt,
                max_attempts=int(settings.PROCESSING["MAX_ATTEMPTS"]),
                run_after=run_after,
            )
    except IntegrityError:
        logger.info(
            "doc=%s enqueue skipped: a live job already exists (attempt=%s)",
            document.id,
            attempt,
        )
        return None

    record_event(
        document=document,
        job=job,
        event_type=EventType.JOB_ENQUEUED,
        message=message
        or (
            f"Attempt {attempt} queued"
            + (f", not before {run_after.isoformat(timespec='seconds')}" if delay else "")
        ),
        actor=actor,
        context={
            "job_id": job.pk,
            "attempt": attempt,
            "max_attempts": job.max_attempts,
            "run_after": run_after.isoformat(),
        },
    )
    return job


def claim_next_job(worker_id: str) -> ProcessingJob | None:
    """Atomically take ownership of the next due job.

    ``skip_locked`` means concurrent workers step over each other's rows
    instead of blocking, so scaling the worker service out is safe. The
    document is locked in the same transaction and moved to PROCESSING, which
    is what stops a second worker from starting the same document via a
    different job row.
    """

    now = timezone.now()
    with transaction.atomic():
        job = (
            ProcessingJob.objects.select_for_update(skip_locked=True)
            .filter(status=JobStatus.QUEUED, run_after__lte=now)
            .order_by("run_after", "created_at")
            .first()
        )
        if job is None:
            return None

        # Lock order is always job -> document, everywhere, to avoid deadlocks.
        document = Document.objects.select_for_update().get(pk=job.document_id)

        job.status = JobStatus.RUNNING
        job.locked_by = worker_id
        job.locked_at = now
        job.started_at = now
        job.save(update_fields=["status", "locked_by", "locked_at", "started_at", "updated_at"])

        transition(
            document=document,
            to_status=DocumentStatus.PROCESSING,
            event_type=EventType.PROCESSING_STARTED,
            message=f"Processing started (attempt {job.attempt} of {job.max_attempts})",
            job=job,
            actor=worker_id,
            extra_fields={"attempts": job.attempt},
        )

        job.document = document
        return job


def due_job_count() -> int:
    return ProcessingJob.objects.filter(
        status=JobStatus.QUEUED, run_after__lte=timezone.now()
    ).count()
