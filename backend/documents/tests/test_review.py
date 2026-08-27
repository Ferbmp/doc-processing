from decimal import Decimal

import pytest

from documents.models import AuditEvent, ExtractionResult
from documents.services.review import ReviewError, apply_review
from documents.states import DocumentStatus, EventType

pytestmark = pytest.mark.django_db


def test_approving_an_incomplete_record_is_refused(make_document, drain):
    document = make_document("arithmetic_mismatch")
    drain()

    with pytest.raises(ReviewError) as excinfo:
        apply_review(document.id, action="approve", reviewer="fernando")

    assert excinfo.value.code == "incomplete_record"
    assert any("missing total" in reason for reason in excinfo.value.details)
    document.refresh_from_db()
    assert document.status == DocumentStatus.REVIEW_REQUIRED


def test_approving_with_corrections_completes_the_document(make_document, drain):
    document = make_document("arithmetic_mismatch")
    drain()
    result = ExtractionResult.objects.get(document=document)
    corrected_total = result.subtotal + result.tax

    apply_review(
        document.id,
        action="approve",
        reviewer="fernando",
        notes="checked against the PDF",
        corrections={"total": corrected_total},
    )

    document.refresh_from_db()
    result.refresh_from_db()
    assert document.status == DocumentStatus.COMPLETED
    assert result.total == corrected_total
    assert result.needs_review is False
    assert result.review_reasons == []
    assert result.corrections == {"total": str(corrected_total)}
    approval = AuditEvent.objects.get(document=document, event_type=EventType.REVIEW_APPROVED)
    assert approval.actor == "reviewer:fernando"


def test_corrections_still_have_to_add_up(make_document, drain):
    document = make_document("arithmetic_mismatch")
    drain()

    with pytest.raises(ReviewError) as excinfo:
        apply_review(
            document.id,
            action="approve",
            reviewer="fernando",
            corrections={"total": Decimal("999999.00")},
        )

    assert excinfo.value.code == "incomplete_record"
    assert any("does not equal subtotal + tax" in reason for reason in excinfo.value.details)


def test_rejecting_keeps_the_record_but_never_accepts_it(make_document, drain):
    document = make_document("low_confidence")
    drain()

    apply_review(document.id, action="reject", reviewer="fernando", notes="not our invoice")

    document.refresh_from_db()
    result = document.result
    assert document.status == DocumentStatus.REJECTED
    assert result.needs_review is True
    assert result.review_action == "reject"
    assert AuditEvent.objects.filter(
        document=document, event_type=EventType.REVIEW_REJECTED
    ).exists()


def test_a_reviewer_cannot_approve_a_second_copy_of_an_accepted_invoice(make_document, drain):
    make_document("success", invoice_number="ONLY-ONCE")
    second = make_document("success", invoice_number="ONLY-ONCE", note="second scan")
    drain()
    second.refresh_from_db()
    assert second.status == DocumentStatus.REVIEW_REQUIRED

    with pytest.raises(ReviewError) as excinfo:
        apply_review(second.id, action="approve", reviewer="fernando")

    assert excinfo.value.code == "duplicate_invoice"
    second.refresh_from_db()
    assert second.status == DocumentStatus.REVIEW_REQUIRED
    assert ExtractionResult.objects.filter(
        invoice_number="ONLY-ONCE", needs_review=False
    ).count() == 1


def test_only_documents_awaiting_review_can_be_reviewed(make_document, drain):
    document = make_document("success")
    drain()

    with pytest.raises(ReviewError) as excinfo:
        apply_review(document.id, action="approve", reviewer="fernando")

    assert excinfo.value.code == "wrong_status"
