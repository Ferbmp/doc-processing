import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from .states import LIVE_JOB_STATUSES, DocumentStatus, EventType, JobStatus

MONEY = {"max_digits": 14, "decimal_places": 2}


class InputFormat(models.TextChoices):
    JSON = "json", "JSON"
    TEXT = "text", "Text"


class Document(models.Model):
    """An inbound financial document and its current lifecycle state."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    source_reference = models.CharField(
        max_length=255,
        blank=True,
        help_text="Caller supplied reference, e.g. an email id. Informational only.",
    )
    input_format = models.CharField(max_length=8, choices=InputFormat.choices)
    raw_text = models.TextField(help_text="Exactly what was submitted, byte for byte.")
    raw_payload = models.JSONField(
        null=True,
        blank=True,
        help_text="Parsed payload when the submission was valid JSON.",
    )

    # Submission-level idempotency key: sha256 over the canonicalised payload
    # plus the forced simulator outcome. Two identical submissions collapse
    # onto one document instead of producing two financial records.
    content_hash = models.CharField(max_length=64, unique=True, editable=False)

    forced_outcome = models.CharField(
        max_length=32,
        blank=True,
        help_text="Test hook: pins the simulated AI service to a specific outcome.",
    )

    status = models.CharField(
        max_length=32,
        choices=DocumentStatus.choices,
        default=DocumentStatus.RECEIVED,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(
        default=0, help_text="Extraction attempts consumed so far."
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = [models.Index(fields=("status", "created_at"))]

    def __str__(self) -> str:
        return f"Document {self.id} ({self.status})"

    @property
    def is_decided(self) -> bool:
        from .states import DECIDED_STATUSES

        return self.status in DECIDED_STATUSES


class ProcessingJob(models.Model):
    """One unit of queued work: attempt N of extracting a document.

    Retries are new rows rather than mutations of the previous row, so the
    job table doubles as an attempt history. The partial unique index below
    guarantees a document never has two live jobs, which is what keeps
    duplicate enqueues from turning into duplicate processing.
    """

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="jobs")
    status = models.CharField(
        max_length=16, choices=JobStatus.choices, default=JobStatus.QUEUED, db_index=True
    )
    attempt = models.PositiveIntegerField(default=1)
    max_attempts = models.PositiveIntegerField(default=3)

    run_after = models.DateTimeField(
        db_index=True, help_text="Worker ignores this job until now() passes this point."
    )

    locked_by = models.CharField(max_length=128, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    error_type = models.CharField(max_length=128, blank=True)
    error_message = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("run_after", "created_at")
        constraints = [
            models.UniqueConstraint(
                fields=("document",),
                condition=Q(status__in=LIVE_JOB_STATUSES),
                name="unique_live_job_per_document",
            ),
        ]
        indexes = [models.Index(fields=("status", "run_after"))]

    def __str__(self) -> str:
        return f"Job {self.pk} doc={self.document_id} attempt={self.attempt} ({self.status})"

    @property
    def has_attempts_left(self) -> bool:
        return self.attempt < self.max_attempts


class ExtractionResult(models.Model):
    """The financial record extracted from a document.

    One row per document, enforced by the database via the one to one primary
    key. Re-running a job can only ever update this row, never add a second
    one, so duplicate execution cannot create duplicate financial records.
    """

    document = models.OneToOneField(
        Document, on_delete=models.CASCADE, related_name="result", primary_key=True
    )

    attempt = models.PositiveIntegerField(help_text="Attempt that produced this result.")

    vendor_name = models.CharField(max_length=255, null=True, blank=True)
    invoice_number = models.CharField(max_length=128, null=True, blank=True)
    invoice_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=3, null=True, blank=True)

    subtotal = models.DecimalField(null=True, blank=True, **MONEY)
    tax = models.DecimalField(null=True, blank=True, **MONEY)
    total = models.DecimalField(null=True, blank=True, **MONEY)

    line_items = models.JSONField(default=list, blank=True)

    confidence = models.FloatField()
    needs_review = models.BooleanField(default=True, db_index=True)
    review_reasons = models.JSONField(default=list, blank=True)

    raw_extraction = models.JSONField(
        default=dict,
        blank=True,
        help_text="Untouched response from the extraction service, kept for audit.",
    )

    extracted_at = models.DateTimeField()

    review_action = models.CharField(max_length=16, blank=True)
    reviewed_by = models.CharField(max_length=128, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    corrections = models.JSONField(
        default=dict, blank=True, help_text="Field level edits applied by the reviewer."
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(subtotal__isnull=True) | Q(subtotal__gte=0),
                name="extraction_subtotal_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(tax__isnull=True) | Q(tax__gte=0),
                name="extraction_tax_non_negative",
            ),
            models.CheckConstraint(
                condition=Q(total__isnull=True) | Q(total__gte=0),
                name="extraction_total_non_negative",
            ),
            # A stored total must agree with its components. Extractions whose
            # arithmetic does not add up keep total NULL and carry a review
            # reason instead, so the database never holds an inconsistent
            # financial record.
            models.CheckConstraint(
                condition=(
                    Q(total__isnull=True)
                    | Q(subtotal__isnull=True)
                    | Q(tax__isnull=True)
                    | Q(total=F("subtotal") + F("tax"))
                ),
                name="extraction_total_matches_components",
            ),
            models.CheckConstraint(
                condition=Q(confidence__gte=0) & Q(confidence__lte=1),
                name="extraction_confidence_in_range",
            ),
            # Accepted records are unique per vendor + invoice number. Records
            # parked in review may collide, which is exactly how a suspected
            # duplicate invoice reaches a human instead of the ledger.
            models.UniqueConstraint(
                fields=("vendor_name", "invoice_number"),
                condition=Q(needs_review=False),
                name="unique_accepted_invoice_per_vendor",
            ),
        ]

    def __str__(self) -> str:
        return f"Result doc={self.document_id} total={self.total} review={self.needs_review}"


class AuditEvent(models.Model):
    """Append-only history of everything that happened to a document.

    Rows are immutable: ``save`` refuses updates and ``delete`` raises. The
    timeline is the product feature that answers "what happened to this
    document", so it must not be rewritable by application code.
    """

    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="events")
    job = models.ForeignKey(
        ProcessingJob, on_delete=models.SET_NULL, null=True, blank=True, related_name="events"
    )

    event_type = models.CharField(max_length=48, choices=EventType.choices)
    message = models.TextField()
    attempt = models.PositiveIntegerField(null=True, blank=True)
    from_status = models.CharField(max_length=32, blank=True)
    to_status = models.CharField(max_length=32, blank=True)
    actor = models.CharField(
        max_length=128, blank=True, help_text="worker id, 'api', or 'reviewer:<name>'."
    )
    context = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("created_at", "id")
        indexes = [models.Index(fields=("document", "created_at"))]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.event_type} doc={self.document_id}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError("Audit events are append-only and cannot be modified.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit events are append-only and cannot be deleted.")
