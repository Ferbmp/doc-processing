"""Populate the system with one document per interesting outcome."""

import json
from decimal import Decimal

from django.core.management.base import BaseCommand

from documents.ai.simulator import SimulatedOutcome
from documents.services.submission import submit_document

TWO_PLACES = Decimal("0.01")
TAX_RATE = Decimal("0.20")


def invoice(vendor: str, number: str, items: list[tuple[str, int, str]]) -> str:
    """Build an internally consistent invoice payload.

    Totals are derived from the line items rather than typed in, so the only
    documents that fail validation are the ones the simulator deliberately
    corrupts.
    """

    line_items = [
        {
            "description": description,
            "quantity": quantity,
            "unit_price": unit_price,
            "amount": str((Decimal(unit_price) * quantity).quantize(TWO_PLACES)),
        }
        for description, quantity, unit_price in items
    ]
    subtotal = sum(
        (Decimal(item["amount"]) for item in line_items), Decimal("0.00")
    ).quantize(TWO_PLACES)
    tax = (subtotal * TAX_RATE).quantize(TWO_PLACES)

    return json.dumps(
        {
            "vendor_name": vendor,
            "invoice_number": number,
            "invoice_date": "2026-08-14",
            "currency": "GBP",
            "line_items": line_items,
            "subtotal": str(subtotal),
            "tax": str(tax),
            "total": str((subtotal + tax).quantize(TWO_PLACES)),
        },
        indent=2,
    )


CONSULTING = [("Consulting, August", 8, "125.00"), ("Travel expenses", 1, "212.50")]
HOSTING = [("Managed hosting", 1, "840.00"), ("Support hours", 6, "95.00")]
PRINT = [("Brochures, 5000 units", 1, "455.00")]

SCENARIOS = [
    (
        "clean invoice, accepted automatically",
        invoice("Northwind Supplies Ltd", "INV-1001", CONSULTING),
        SimulatedOutcome.SUCCESS,
    ),
    (
        "flaky service: fails once, then succeeds on retry",
        invoice("Acme Logistics", "ACM-4417", HOSTING),
        SimulatedOutcome.FLAKY,
    ),
    (
        "model returns partial data, needs review",
        invoice("Blue Harbour Consulting", "BH-2026-08", CONSULTING),
        SimulatedOutcome.INCOMPLETE,
    ),
    (
        "stated total disagrees with subtotal + tax",
        invoice("Kestrel Print & Design", "KPD-778", PRINT),
        SimulatedOutcome.ARITHMETIC_MISMATCH,
    ),
    (
        "low confidence extraction, from plain text input",
        "Vendor: Harbour Coffee Co\nInvoice No: HC-9931\nDate: 2026-08-02\n"
        "Currency: GBP\nSubtotal: 82.50\nTax: 16.50\nTotal: 99.00\n",
        SimulatedOutcome.LOW_CONFIDENCE,
    ),
    (
        "extraction service keeps failing, exhausts retries",
        invoice("Vantage Cloud Services", "VCS-55021", HOSTING),
        SimulatedOutcome.TRANSIENT_FAILURE,
    ),
    (
        "unrecognisable document, no retries",
        "Scanned page 3 of 3. No invoice data on this page.",
        SimulatedOutcome.PERMANENT_FAILURE,
    ),
    (
        "second scan of INV-1001, caught as a duplicate invoice",
        invoice(
            "Northwind Supplies Ltd",
            "INV-1001",
            [("Consulting, August", 8, "125.00"), ("Travel expenses (rescan)", 1, "212.50")],
        ),
        SimulatedOutcome.SUCCESS,
    ),
]


class Command(BaseCommand):
    help = "Submit a spread of demo documents covering every processing outcome."

    def handle(self, *args, **options):
        for description, content, outcome in SCENARIOS:
            document, created = submit_document(
                content=content,
                source_reference=f"seed_demo: {description}",
                forced_outcome=outcome,
                actor="seed_demo",
            )
            verb = "submitted" if created else "already existed"
            self.stdout.write(f"{verb}: {document.id}  [{outcome}]  {description}")

        self.stdout.write(
            self.style.SUCCESS(
                "\nDemo documents queued. The worker service will pick them up; "
                "run 'python manage.py process_documents --once' to drain them now."
            )
        )
