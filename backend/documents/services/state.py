"""The only sanctioned way to change a document's status.

Keeping transitions and audit writes in one function means the two can never
drift apart: if a status changed, there is an audit row explaining it, written
in the same transaction.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping

from ..models import AuditEvent, Document, ProcessingJob
from ..states import ALLOWED_TRANSITIONS, InvalidTransition

logger = logging.getLogger(__name__)


def record_event(
    *,
    document: Document,
    event_type: str,
    message: str,
    job: ProcessingJob | None = None,
    attempt: int | None = None,
    actor: str = "",
    context: Mapping[str, Any] | None = None,
    from_status: str = "",
    to_status: str = "",
) -> AuditEvent:
    """Append one immutable entry to a document's timeline."""

    event = AuditEvent.objects.create(
        document=document,
        job=job,
        event_type=event_type,
        message=message,
        attempt=attempt if attempt is not None else (job.attempt if job else None),
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        context=dict(context or {}),
    )
    logger.info(
        "doc=%s event=%s attempt=%s actor=%s %s",
        document.id,
        event_type,
        event.attempt,
        actor or "-",
        message,
    )
    return event


def transition(
    *,
    document: Document,
    to_status: str,
    event_type: str,
    message: str,
    job: ProcessingJob | None = None,
    actor: str = "",
    attempt: int | None = None,
    context: Mapping[str, Any] | None = None,
    extra_fields: Mapping[str, Any] | None = None,
) -> AuditEvent:
    """Move ``document`` to ``to_status``, refusing illegal moves.

    Callers are expected to be holding a row lock on ``document`` (see
    ``select_for_update`` in the queue and processing services), which is what
    makes the check-then-write safe under concurrency.
    """

    from_status = document.status
    if to_status not in ALLOWED_TRANSITIONS.get(from_status, frozenset()):
        raise InvalidTransition(document.id, from_status, to_status)

    update_fields = ["status", "updated_at"]
    document.status = to_status
    for field, value in (extra_fields or {}).items():
        setattr(document, field, value)
        update_fields.append(field)

    document.save(update_fields=update_fields)

    return record_event(
        document=document,
        event_type=event_type,
        message=message,
        job=job,
        attempt=attempt,
        actor=actor,
        context=context,
        from_status=from_status,
        to_status=to_status,
    )
