import pytest

from documents.models import AuditEvent, Document, ProcessingJob
from documents.services.queue import enqueue_job
from documents.services.submission import SubmissionError, submit_document
from documents.states import DocumentStatus, EventType, JobStatus
from documents.tests.conftest import invoice_json

pytestmark = pytest.mark.django_db


def test_submission_creates_document_and_first_job():
    document, created = submit_document(content=invoice_json(), source_reference="inbox")

    assert created is True
    assert document.status == DocumentStatus.RECEIVED
    job = ProcessingJob.objects.get(document=document)
    assert (job.attempt, job.status) == (1, JobStatus.QUEUED)
    assert AuditEvent.objects.filter(
        document=document, event_type=EventType.DOCUMENT_RECEIVED
    ).exists()


def test_identical_resubmission_collapses_onto_the_same_document():
    first, created_first = submit_document(content=invoice_json())
    second, created_second = submit_document(content=invoice_json())

    assert created_first is True
    assert created_second is False
    assert first.id == second.id
    assert Document.objects.count() == 1
    # Still only one job: the duplicate did not queue more work.
    assert ProcessingJob.objects.count() == 1
    assert AuditEvent.objects.filter(
        event_type=EventType.DUPLICATE_SUBMISSION_IGNORED
    ).count() == 1


def test_key_order_does_not_defeat_deduplication():
    submit_document(content='{"invoice_number": "A-1", "total": "10.00"}')
    _, created = submit_document(content='{"total": "10.00", "invoice_number": "A-1"}')

    assert created is False
    assert Document.objects.count() == 1


def test_different_forced_outcome_is_a_different_document():
    submit_document(content=invoice_json(), forced_outcome="success")
    _, created = submit_document(content=invoice_json(), forced_outcome="flaky")

    assert created is True
    assert Document.objects.count() == 2


def test_plain_text_submissions_are_accepted():
    document, created = submit_document(
        content="Vendor: Harbour Coffee\nInvoice No: HC-1\nTotal: 99.00\n"
    )

    assert created is True
    assert document.input_format == "text"
    assert document.raw_payload is None


def test_empty_submission_is_rejected():
    with pytest.raises(SubmissionError):
        submit_document(content="   \n ")


def test_a_document_cannot_have_two_live_jobs(make_document):
    document = make_document()

    second = enqueue_job(document, attempt=1)

    assert second is None
    assert ProcessingJob.objects.filter(document=document).count() == 1
