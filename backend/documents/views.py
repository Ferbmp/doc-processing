from django.db.models import Count, Prefetch
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .ai.simulator import SimulatedOutcome
from .models import AuditEvent, Document, ProcessingJob
from .serializers import (
    DocumentDetailSerializer,
    DocumentSummarySerializer,
    ReviewSerializer,
    SubmitDocumentSerializer,
)
from .services.queue import due_job_count
from .services.review import ReviewError, apply_review
from .services.submission import RetryNotAllowed, SubmissionError, request_manual_retry, submit_document
from .states import DocumentStatus


def _error(message: str, *, code: str, http_status: int, details=None) -> Response:
    body = {"detail": message, "code": code}
    if details:
        body["details"] = details
    return Response(body, status=http_status)


class HealthView(APIView):
    def get(self, request):
        return Response(
            {
                "status": "ok",
                "time": timezone.now(),
                "jobs_due": due_job_count(),
            }
        )


class DocumentListCreateView(generics.ListAPIView):
    serializer_class = DocumentSummarySerializer

    def get_queryset(self):
        queryset = Document.objects.select_related("result")
        requested_status = self.request.query_params.get("status")
        if requested_status in DocumentStatus.values:
            queryset = queryset.filter(status=requested_status)
        return queryset

    def post(self, request):
        payload = SubmitDocumentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        simulate = data.get("simulate") or SimulatedOutcome.RANDOM
        try:
            document, created = submit_document(
                content=data["content"],
                source_reference=data.get("source_reference", ""),
                forced_outcome="" if simulate == SimulatedOutcome.RANDOM else simulate,
            )
        except SubmissionError as exc:
            return _error(str(exc), code="invalid_submission", http_status=400)

        body = DocumentSummarySerializer(document).data
        # 201 for a new document, 200 for "we already have this one". The
        # caller can retry a submission safely and always learn where the
        # document ended up.
        body["duplicate"] = not created
        return Response(body, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class DocumentDetailView(generics.RetrieveAPIView):
    serializer_class = DocumentDetailSerializer
    queryset = Document.objects.select_related("result").prefetch_related(
        Prefetch("events", queryset=AuditEvent.objects.order_by("created_at", "id")),
        Prefetch("jobs", queryset=ProcessingJob.objects.order_by("attempt", "created_at")),
    )


class DocumentRetryView(APIView):
    def post(self, request, pk):
        if not Document.objects.filter(pk=pk).exists():
            return _error("Document not found.", code="not_found", http_status=404)
        try:
            request_manual_retry(pk, actor=request.data.get("actor") or "api")
        except RetryNotAllowed as exc:
            return _error(str(exc), code="retry_not_allowed", http_status=409)
        return Response(_detail_body(pk))


class DocumentReviewView(APIView):
    def post(self, request, pk):
        if not Document.objects.filter(pk=pk).exists():
            return _error("Document not found.", code="not_found", http_status=404)

        payload = ReviewSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        try:
            apply_review(
                pk,
                action=data["action"],
                reviewer=data.get("reviewer") or "unnamed reviewer",
                notes=data.get("notes", ""),
                corrections=data.get("corrections") or {},
            )
        except ReviewError as exc:
            http_status = 409 if exc.code in {"duplicate_invoice", "wrong_status"} else 400
            return _error(str(exc), code=exc.code, http_status=http_status, details=exc.details)

        return Response(_detail_body(pk))


class StatsView(APIView):
    def get(self, request):
        counts = {row["status"]: row["n"] for row in Document.objects.values("status").annotate(n=Count("id"))}
        return Response(
            {
                "total": sum(counts.values()),
                "by_status": {value: counts.get(value, 0) for value in DocumentStatus.values},
                "jobs_due": due_job_count(),
            }
        )


def _detail_body(pk):
    document = DocumentDetailView.queryset.get(pk=pk)
    return DocumentDetailSerializer(document).data
