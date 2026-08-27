from django.contrib import admin

from .models import AuditEvent, Document, ExtractionResult, ProcessingJob


class AuditEventInline(admin.TabularInline):
    model = AuditEvent
    extra = 0
    can_delete = False
    fields = ("created_at", "event_type", "attempt", "actor", "message")
    readonly_fields = fields
    ordering = ("created_at",)

    def has_add_permission(self, request, obj):
        return False


class ProcessingJobInline(admin.TabularInline):
    model = ProcessingJob
    extra = 0
    can_delete = False
    fields = ("attempt", "status", "run_after", "locked_by", "finished_at", "error_type")
    readonly_fields = fields

    def has_add_permission(self, request, obj):
        return False


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("id", "status", "attempts", "source_reference", "created_at")
    list_filter = ("status", "input_format")
    search_fields = ("id", "source_reference", "content_hash")
    readonly_fields = ("content_hash", "created_at", "updated_at")
    inlines = [ProcessingJobInline, AuditEventInline]


@admin.register(ExtractionResult)
class ExtractionResultAdmin(admin.ModelAdmin):
    list_display = (
        "document_id",
        "vendor_name",
        "invoice_number",
        "total",
        "confidence",
        "needs_review",
    )
    list_filter = ("needs_review", "currency")
    search_fields = ("vendor_name", "invoice_number")


@admin.register(ProcessingJob)
class ProcessingJobAdmin(admin.ModelAdmin):
    list_display = ("id", "document_id", "attempt", "status", "run_after", "locked_by")
    list_filter = ("status",)


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "document_id", "event_type", "attempt", "actor")
    list_filter = ("event_type",)
    search_fields = ("document__id", "message")

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
