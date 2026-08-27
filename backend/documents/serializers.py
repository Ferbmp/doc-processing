from rest_framework import serializers

from .ai.simulator import SimulatedOutcome
from .models import AuditEvent, Document, ExtractionResult, ProcessingJob
from .services.review import APPROVE, REJECT


class AuditEventSerializer(serializers.ModelSerializer):
    event_label = serializers.CharField(source="get_event_type_display", read_only=True)

    class Meta:
        model = AuditEvent
        fields = (
            "id",
            "event_type",
            "event_label",
            "message",
            "attempt",
            "from_status",
            "to_status",
            "actor",
            "context",
            "created_at",
        )


class ProcessingJobSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProcessingJob
        fields = (
            "id",
            "status",
            "attempt",
            "max_attempts",
            "run_after",
            "locked_by",
            "locked_at",
            "started_at",
            "finished_at",
            "error_type",
            "error_message",
            "created_at",
        )


class ExtractionResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExtractionResult
        fields = (
            "attempt",
            "vendor_name",
            "invoice_number",
            "invoice_date",
            "currency",
            "subtotal",
            "tax",
            "total",
            "line_items",
            "confidence",
            "needs_review",
            "review_reasons",
            "raw_extraction",
            "extracted_at",
            "review_action",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "corrections",
        )


class DocumentSummarySerializer(serializers.ModelSerializer):
    status_label = serializers.CharField(source="get_status_display", read_only=True)
    vendor_name = serializers.SerializerMethodField()
    invoice_number = serializers.SerializerMethodField()
    total = serializers.SerializerMethodField()
    currency = serializers.SerializerMethodField()
    review_reasons = serializers.SerializerMethodField()

    class Meta:
        model = Document
        fields = (
            "id",
            "status",
            "status_label",
            "source_reference",
            "input_format",
            "forced_outcome",
            "attempts",
            "created_at",
            "updated_at",
            "vendor_name",
            "invoice_number",
            "total",
            "currency",
            "review_reasons",
        )

    def _result(self, obj):
        return getattr(obj, "result", None)

    def get_vendor_name(self, obj):
        result = self._result(obj)
        return result.vendor_name if result else None

    def get_invoice_number(self, obj):
        result = self._result(obj)
        return result.invoice_number if result else None

    def get_total(self, obj):
        result = self._result(obj)
        return str(result.total) if result and result.total is not None else None

    def get_currency(self, obj):
        result = self._result(obj)
        return result.currency if result else None

    def get_review_reasons(self, obj):
        result = self._result(obj)
        return result.review_reasons if result else []


class DocumentDetailSerializer(DocumentSummarySerializer):
    result = ExtractionResultSerializer(read_only=True)
    jobs = ProcessingJobSerializer(many=True, read_only=True)
    events = AuditEventSerializer(many=True, read_only=True)

    class Meta(DocumentSummarySerializer.Meta):
        fields = DocumentSummarySerializer.Meta.fields + (
            "raw_text",
            "raw_payload",
            "content_hash",
            "result",
            "jobs",
            "events",
        )


class SubmitDocumentSerializer(serializers.Serializer):
    content = serializers.CharField(trim_whitespace=False)
    source_reference = serializers.CharField(
        required=False, allow_blank=True, default="", max_length=255
    )
    simulate = serializers.ChoiceField(
        choices=SimulatedOutcome.ALL,
        required=False,
        allow_blank=True,
        default=SimulatedOutcome.RANDOM,
        help_text="Pin the simulated extraction service to a specific outcome.",
    )


class CorrectionsSerializer(serializers.Serializer):
    vendor_name = serializers.CharField(required=False, allow_null=True, max_length=255)
    invoice_number = serializers.CharField(required=False, allow_null=True, max_length=128)
    invoice_date = serializers.DateField(required=False, allow_null=True)
    currency = serializers.CharField(required=False, allow_null=True, max_length=3)
    subtotal = serializers.DecimalField(
        required=False, allow_null=True, max_digits=14, decimal_places=2
    )
    tax = serializers.DecimalField(
        required=False, allow_null=True, max_digits=14, decimal_places=2
    )
    total = serializers.DecimalField(
        required=False, allow_null=True, max_digits=14, decimal_places=2
    )


class ReviewSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=(APPROVE, REJECT))
    reviewer = serializers.CharField(max_length=128, default="unnamed reviewer")
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    corrections = CorrectionsSerializer(required=False)
