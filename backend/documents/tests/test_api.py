import json

import pytest

from documents.models import Document
from documents.states import DocumentStatus
from documents.tests.conftest import invoice_json

pytestmark = pytest.mark.django_db


def post(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type="application/json")


def test_health_endpoint(client):
    response = client.get("/api/health/")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_submit_returns_201_then_200_for_a_duplicate(client):
    first = post(
        client,
        "/api/documents/",
        {"content": invoice_json(), "source_reference": "inbox", "simulate": "success"},
    )
    second = post(
        client,
        "/api/documents/",
        {"content": invoice_json(), "source_reference": "inbox", "simulate": "success"},
    )

    assert first.status_code == 201
    assert first.json()["duplicate"] is False
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert first.json()["id"] == second.json()["id"]
    assert Document.objects.count() == 1


def test_submit_rejects_empty_content(client):
    response = post(client, "/api/documents/", {"content": "   "})

    assert response.status_code == 400


def test_detail_exposes_the_timeline_and_the_record(client, make_document, drain):
    document = make_document("success")
    drain()

    body = client.get(f"/api/documents/{document.id}/").json()

    assert body["status"] == DocumentStatus.COMPLETED
    assert body["result"]["needs_review"] is False
    assert [event["event_type"] for event in body["events"]][0] == "document_received"
    assert len(body["jobs"]) == 1
    assert body["events"][-1]["event_type"] == "result_accepted"


def test_list_can_filter_by_status(client, make_document, drain):
    make_document("success")
    make_document("low_confidence", invoice_number="LOW-1")
    drain()

    completed = client.get("/api/documents/?status=completed").json()
    review = client.get("/api/documents/?status=review_required").json()

    assert completed["count"] == 1
    assert review["count"] == 1


def test_retry_endpoint_requeues_a_failed_document(client, make_document, drain):
    document = make_document("transient_failure")
    drain()
    document.refresh_from_db()
    assert document.status == DocumentStatus.FAILED

    response = post(client, f"/api/documents/{document.id}/retry/", {})

    assert response.status_code == 200
    assert response.json()["status"] == DocumentStatus.RETRY_SCHEDULED


def test_retry_is_rejected_for_a_completed_document(client, make_document, drain):
    document = make_document("success")
    drain()

    response = post(client, f"/api/documents/{document.id}/retry/", {})

    assert response.status_code == 409
    assert response.json()["code"] == "retry_not_allowed"


def test_review_endpoint_reports_blocking_reasons(client, make_document, drain):
    document = make_document("arithmetic_mismatch")
    drain()

    response = post(
        client,
        f"/api/documents/{document.id}/review/",
        {"action": "approve", "reviewer": "fernando"},
    )

    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "incomplete_record"
    assert any("missing total" in item for item in body["details"])


def test_review_endpoint_approves_with_corrections(client, make_document, drain):
    document = make_document("arithmetic_mismatch")
    drain()
    document.refresh_from_db()
    total = document.result.subtotal + document.result.tax

    response = post(
        client,
        f"/api/documents/{document.id}/review/",
        {
            "action": "approve",
            "reviewer": "fernando",
            "notes": "verified",
            "corrections": {"total": str(total)},
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == DocumentStatus.COMPLETED


def test_stats_endpoint_counts_by_status(client, make_document, drain):
    make_document("success")
    drain()

    body = client.get("/api/stats/").json()

    assert body["total"] == 1
    assert body["by_status"]["completed"] == 1
