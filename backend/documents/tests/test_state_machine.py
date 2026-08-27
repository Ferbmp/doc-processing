import pytest
from django.core.exceptions import ValidationError

from documents.models import AuditEvent
from documents.services.state import record_event, transition
from documents.states import ALLOWED_TRANSITIONS, DocumentStatus, EventType, InvalidTransition

pytestmark = pytest.mark.django_db


def test_forbidden_transition_is_rejected(make_document):
    document = make_document()
    assert document.status == DocumentStatus.RECEIVED

    with pytest.raises(InvalidTransition):
        transition(
            document=document,
            to_status=DocumentStatus.COMPLETED,
            event_type=EventType.RESULT_ACCEPTED,
            message="skipping straight to completed",
        )

    document.refresh_from_db()
    assert document.status == DocumentStatus.RECEIVED


def test_terminal_states_have_no_way_out():
    assert ALLOWED_TRANSITIONS[DocumentStatus.COMPLETED] == frozenset()
    assert ALLOWED_TRANSITIONS[DocumentStatus.REJECTED] == frozenset()


def test_transition_records_an_audit_event_with_both_ends(make_document):
    document = make_document()

    transition(
        document=document,
        to_status=DocumentStatus.PROCESSING,
        event_type=EventType.PROCESSING_STARTED,
        message="off we go",
        actor="test",
    )

    event = AuditEvent.objects.filter(event_type=EventType.PROCESSING_STARTED).get()
    assert event.from_status == DocumentStatus.RECEIVED
    assert event.to_status == DocumentStatus.PROCESSING
    assert event.actor == "test"
    document.refresh_from_db()
    assert document.status == DocumentStatus.PROCESSING


def test_audit_events_cannot_be_edited_or_deleted(make_document):
    document = make_document()
    event = record_event(
        document=document,
        event_type=EventType.DOCUMENT_RECEIVED,
        message="original wording",
    )

    event.message = "rewritten history"
    with pytest.raises(ValidationError):
        event.save()

    with pytest.raises(ValidationError):
        event.delete()

    event.refresh_from_db()
    assert event.message == "original wording"
