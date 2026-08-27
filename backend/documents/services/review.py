"""Human review: the escape hatch that keeps bad data out of the ledger.

Approving is not a rubber stamp. The same validation that refused to
auto-accept the extraction runs again on the reviewer's corrected figures, and
the ``unique_accepted_invoice_per_vendor`` index gets the final say on whether
this invoice may be accepted at all.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import Document, ExtractionResult
from ..states import DocumentStatus, EventType
from .state import transition
from .validation import blocking_reasons_for_acceptance

APPROVE = "approve"
REJECT = "reject"

CORRECTABLE_FIELDS = (
    "vendor_name",
    "invoice_number",
    "invoice_date",
    "currency",
    "subtotal",
    "tax",
    "total",
)


class ReviewError(Exception):
    def __init__(self, message: str, *, code: str = "invalid", details: Any = None) -> None:
        self.code = code
        self.details = details
        super().__init__(message)


def _serialisable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def apply_review(
    document_id,
    *,
    action: str,
    reviewer: str,
    notes: str = "",
    corrections: dict[str, Any] | None = None,
) -> Document:
    corrections = {k: v for k, v in (corrections or {}).items() if k in CORRECTABLE_FIELDS}

    with transaction.atomic():
        document = Document.objects.select_for_update().get(pk=document_id)

        if document.status != DocumentStatus.REVIEW_REQUIRED:
            raise ReviewError(
                f"Only documents awaiting review can be reviewed; this one is {document.status}.",
                code="wrong_status",
            )

        try:
            result = ExtractionResult.objects.select_for_update().get(document=document)
        except ExtractionResult.DoesNotExist as exc:
            raise ReviewError(
                "This document has no extraction result to review.", code="no_result"
            ) from exc

        if action == REJECT:
            return _reject(document, result, reviewer=reviewer, notes=notes)
        if action == APPROVE:
            return _approve(
                document, result, reviewer=reviewer, notes=notes, corrections=corrections
            )
        raise ReviewError(f"Unknown review action '{action}'.", code="unknown_action")


def _approve(
    document: Document,
    result: ExtractionResult,
    *,
    reviewer: str,
    notes: str,
    corrections: dict[str, Any],
) -> Document:
    proposed = {name: getattr(result, name) for name in CORRECTABLE_FIELDS}
    proposed.update(corrections)

    blocking = blocking_reasons_for_acceptance(proposed)
    if blocking:
        raise ReviewError(
            "These figures cannot be accepted as final.",
            code="incomplete_record",
            details=blocking,
        )

    for name, value in proposed.items():
        setattr(result, name, value)

    result.needs_review = False
    result.review_reasons = []
    result.review_action = APPROVE
    result.reviewed_by = reviewer
    result.reviewed_at = timezone.now()
    result.review_notes = notes
    result.corrections = {k: _serialisable(v) for k, v in corrections.items()}

    try:
        # Savepoint so the duplicate-invoice rejection does not abort the
        # surrounding transaction.
        with transaction.atomic():
            result.save()
    except IntegrityError as exc:
        raise ReviewError(
            f"Invoice {proposed['invoice_number']} from {proposed['vendor_name']} has "
            "already been accepted on another document.",
            code="duplicate_invoice",
        ) from exc

    transition(
        document=document,
        to_status=DocumentStatus.COMPLETED,
        event_type=EventType.REVIEW_APPROVED,
        message=(
            f"Approved by {reviewer}: {result.currency} {result.total} from "
            f"{result.vendor_name} ({result.invoice_number})"
            + (f". Notes: {notes}" if notes else "")
        ),
        actor=f"reviewer:{reviewer}",
        context={"corrections": result.corrections, "notes": notes},
    )
    return document


def _reject(
    document: Document,
    result: ExtractionResult,
    *,
    reviewer: str,
    notes: str,
) -> Document:
    # The record stays in the database, still flagged for review, so the
    # rejection and its reasons remain inspectable.
    result.review_action = REJECT
    result.reviewed_by = reviewer
    result.reviewed_at = timezone.now()
    result.review_notes = notes
    result.save(
        update_fields=[
            "review_action",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "updated_at",
        ]
    )

    transition(
        document=document,
        to_status=DocumentStatus.REJECTED,
        event_type=EventType.REVIEW_REJECTED,
        message=(
            f"Rejected by {reviewer}" + (f": {notes}" if notes else "; no reason given")
        ),
        actor=f"reviewer:{reviewer}",
        context={"notes": notes, "review_reasons": result.review_reasons},
    )
    return document
