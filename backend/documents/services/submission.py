"""Accepting a document, exactly once.

A submission is idempotent on the content of the document. Re-posting the same
invoice (a retried webhook, a double click, a replayed queue message) returns
the document that already exists instead of creating a second one, because the
whole point is to never end up with two financial records for one invoice.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any

from django.db import IntegrityError, transaction

from ..models import Document, InputFormat
from ..states import DocumentStatus, EventType
from .queue import enqueue_job
from .state import record_event, transition

logger = logging.getLogger(__name__)


class SubmissionError(Exception):
    pass


class RetryNotAllowed(Exception):
    pass


def parse_submission(content: str) -> tuple[str, dict[str, Any] | None, str]:
    """Classify the submitted blob and produce a canonical form for hashing.

    Canonicalising means `{"a":1,"b":2}` and `{"b": 2, "a": 1}` are recognised
    as the same document, which is the interesting half of deduplication.
    """

    stripped = (content or "").strip()
    if not stripped:
        raise SubmissionError("Document content is empty.")

    try:
        parsed = json.loads(stripped)
    except ValueError:
        canonical = " ".join(stripped.split())
        return InputFormat.TEXT, None, canonical

    if not isinstance(parsed, dict):
        # A bare list or scalar is legal JSON but not an invoice payload we can
        # index by field, so treat it as text.
        canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"))
        return InputFormat.TEXT, None, canonical

    canonical = json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=str)
    return InputFormat.JSON, parsed, canonical


def compute_content_hash(canonical: str, forced_outcome: str) -> str:
    """Idempotency key for a submission.

    The forced simulator outcome is part of the key so that a reviewer can
    submit the same sample invoice twice to demo two different failure paths
    without the second submission being swallowed as a duplicate.
    """

    digest = hashlib.sha256()
    digest.update(canonical.encode("utf-8"))
    digest.update(b"\x00")
    digest.update((forced_outcome or "").encode("utf-8"))
    return digest.hexdigest()


def submit_document(
    *,
    content: str,
    source_reference: str = "",
    forced_outcome: str = "",
    actor: str = "api",
) -> tuple[Document, bool]:
    """Store a document and queue its first attempt. Returns (document, created)."""

    input_format, payload, canonical = parse_submission(content)

    if not forced_outcome and isinstance(payload, dict):
        # Convenience for curl users: {"_simulate": "flaky", ...}
        forced_outcome = str(payload.get("_simulate") or "").strip().lower()

    content_hash = compute_content_hash(canonical, forced_outcome)

    try:
        with transaction.atomic():
            document = Document.objects.create(
                source_reference=source_reference,
                input_format=input_format,
                raw_text=content,
                raw_payload=payload,
                content_hash=content_hash,
                forced_outcome=forced_outcome,
                status=DocumentStatus.RECEIVED,
            )
            record_event(
                document=document,
                event_type=EventType.DOCUMENT_RECEIVED,
                message=(
                    f"Document received ({input_format} input, "
                    f"{len(content)} characters)"
                ),
                actor=actor,
                to_status=DocumentStatus.RECEIVED,
                context={
                    "content_hash": content_hash,
                    "source_reference": source_reference,
                    "forced_outcome": forced_outcome or "random",
                },
            )
            # Same transaction as the document insert: a document can never
            # exist without the job that will process it, and a job can never
            # reference a document that was rolled back.
            enqueue_job(document, attempt=1, actor=actor, message="Attempt 1 queued")
        return document, True
    except IntegrityError:
        # Lost the race (or a genuine re-submission): the unique content_hash
        # index means exactly one document survives.
        pass

    existing = Document.objects.get(content_hash=content_hash)
    record_event(
        document=existing,
        event_type=EventType.DUPLICATE_SUBMISSION_IGNORED,
        message=(
            "Duplicate submission ignored: identical content was already received "
            f"at {existing.created_at.isoformat(timespec='seconds')}"
        ),
        actor=actor,
        context={"content_hash": content_hash, "source_reference": source_reference},
    )
    logger.info("duplicate submission collapsed onto doc=%s", existing.id)
    return existing, False


def request_manual_retry(document_id, *, actor: str = "api") -> Document:
    """Put a permanently failed document back in the queue with a fresh budget."""

    with transaction.atomic():
        document = Document.objects.select_for_update().get(pk=document_id)

        if document.status != DocumentStatus.FAILED:
            raise RetryNotAllowed(
                f"Only failed documents can be retried; this one is {document.status}."
            )

        record_event(
            document=document,
            event_type=EventType.MANUAL_RETRY_REQUESTED,
            message="Manual retry requested; the attempt budget has been reset",
            actor=actor,
            context={"previous_attempts": document.attempts},
        )
        transition(
            document=document,
            to_status=DocumentStatus.RETRY_SCHEDULED,
            event_type=EventType.RETRY_SCHEDULED,
            message="Processing retried on operator request",
            actor=actor,
            extra_fields={"attempts": 0},
        )
        job = enqueue_job(
            document,
            attempt=1,
            actor=actor,
            message="Attempt 1 queued by operator",
        )
        if job is None:
            raise RetryNotAllowed("A job for this document is already queued or running.")

        return document
