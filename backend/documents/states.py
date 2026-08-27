"""The document lifecycle, in one place.

Every status change in this codebase goes through
``documents.services.state.transition``, which validates the move against
``ALLOWED_TRANSITIONS`` below and writes an audit event in the same
transaction. Nothing else is allowed to assign ``Document.status``.
"""

from django.db import models


class DocumentStatus(models.TextChoices):
    RECEIVED = "received", "Received"
    PROCESSING = "processing", "Processing"
    RETRY_SCHEDULED = "retry_scheduled", "Retry scheduled"
    REVIEW_REQUIRED = "review_required", "Review required"
    COMPLETED = "completed", "Completed"
    REJECTED = "rejected", "Rejected"
    FAILED = "failed", "Failed"


# A document in one of these states has been decided: no worker may overwrite
# its financial record. Used as the idempotency guard for duplicate execution.
DECIDED_STATUSES = frozenset(
    {
        DocumentStatus.REVIEW_REQUIRED,
        DocumentStatus.COMPLETED,
        DocumentStatus.REJECTED,
    }
)

# Statuses from which no automatic work will ever happen again.
TERMINAL_STATUSES = frozenset(
    {
        DocumentStatus.COMPLETED,
        DocumentStatus.REJECTED,
    }
)

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    DocumentStatus.RECEIVED: frozenset({DocumentStatus.PROCESSING}),
    DocumentStatus.PROCESSING: frozenset(
        {
            DocumentStatus.COMPLETED,
            DocumentStatus.REVIEW_REQUIRED,
            DocumentStatus.RETRY_SCHEDULED,
            DocumentStatus.FAILED,
        }
    ),
    DocumentStatus.RETRY_SCHEDULED: frozenset(
        {
            DocumentStatus.PROCESSING,
            DocumentStatus.FAILED,
        }
    ),
    DocumentStatus.REVIEW_REQUIRED: frozenset(
        {
            DocumentStatus.COMPLETED,
            DocumentStatus.REJECTED,
        }
    ),
    # Operators can put a permanently failed document back in the queue.
    DocumentStatus.FAILED: frozenset({DocumentStatus.RETRY_SCHEDULED}),
    DocumentStatus.COMPLETED: frozenset(),
    DocumentStatus.REJECTED: frozenset(),
}


class InvalidTransition(Exception):
    """Raised when code attempts a status change the lifecycle forbids."""

    def __init__(self, document_id, from_status: str, to_status: str) -> None:
        self.document_id = document_id
        self.from_status = from_status
        self.to_status = to_status
        super().__init__(
            f"Document {document_id}: {from_status} -> {to_status} is not an allowed transition"
        )


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


class JobStatus(models.TextChoices):
    QUEUED = "queued", "Queued"
    RUNNING = "running", "Running"
    SUCCEEDED = "succeeded", "Succeeded"
    FAILED = "failed", "Failed"


# A document may only ever have one job in one of these states.
LIVE_JOB_STATUSES = (JobStatus.QUEUED, JobStatus.RUNNING)


class EventType(models.TextChoices):
    DOCUMENT_RECEIVED = "document_received", "Document received"
    DUPLICATE_SUBMISSION_IGNORED = "duplicate_submission_ignored", "Duplicate submission ignored"
    JOB_ENQUEUED = "job_enqueued", "Job enqueued"
    PROCESSING_STARTED = "processing_started", "Processing started"
    EXTRACTION_SUCCEEDED = "extraction_succeeded", "Extraction completed"
    ATTEMPT_FAILED = "attempt_failed", "Attempt failed"
    RETRY_SCHEDULED = "retry_scheduled", "Processing retried"
    REVIEW_REQUIRED = "review_required", "Result requires review"
    RESULT_ACCEPTED = "result_accepted", "Result accepted"
    REVIEW_APPROVED = "review_approved", "Review approved"
    REVIEW_REJECTED = "review_rejected", "Review rejected"
    PROCESSING_FAILED = "processing_failed", "Processing failed permanently"
    DUPLICATE_EXECUTION_IGNORED = "duplicate_execution_ignored", "Duplicate execution ignored"
    JOB_RECOVERED = "job_recovered", "Stale job recovered"
    MANUAL_RETRY_REQUESTED = "manual_retry_requested", "Manual retry requested"
