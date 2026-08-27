"""Turns a raw extraction into something we are willing to store.

The rule the whole design leans on: the database only ever holds financial
records that are internally consistent. Anything questionable is stored with
``needs_review=True`` and a human-readable list of reasons, and anything
arithmetically impossible has its total withheld rather than persisted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from django.conf import settings

from ..ai.simulator import TWO_PLACES, ExtractionResponse

REQUIRED_FOR_ACCEPTANCE = ("vendor_name", "invoice_number", "currency", "total")

FIELD_LABELS = {
    "vendor_name": "vendor name",
    "invoice_number": "invoice number",
    "currency": "currency",
    "total": "total",
    "subtotal": "subtotal",
    "tax": "tax",
}


@dataclass
class NormalizedResult:
    confidence: float
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    line_items: list[dict[str, Any]] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.review_reasons)

    def as_field_dict(self) -> dict[str, Any]:
        return {
            "vendor_name": self.vendor_name,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "currency": self.currency,
            "subtotal": self.subtotal,
            "tax": self.tax,
            "total": self.total,
        }


def _check_arithmetic(fields: dict[str, Any]) -> list[str]:
    """Reasons why the stated total cannot be trusted."""

    subtotal, tax, total = fields.get("subtotal"), fields.get("tax"), fields.get("total")
    if subtotal is None or tax is None or total is None:
        return []
    expected = (Decimal(subtotal) + Decimal(tax)).quantize(TWO_PLACES)
    if Decimal(total).quantize(TWO_PLACES) != expected:
        return [
            f"stated total {total} does not equal subtotal + tax ({expected})",
        ]
    return []


def normalize_extraction(response: ExtractionResponse) -> NormalizedResult:
    threshold = float(settings.PROCESSING["REVIEW_CONFIDENCE_THRESHOLD"])
    reasons: list[str] = []

    result = NormalizedResult(
        confidence=response.confidence,
        vendor_name=response.vendor_name,
        invoice_number=response.invoice_number,
        invoice_date=response.invoice_date,
        currency=response.currency,
        subtotal=response.subtotal,
        tax=response.tax,
        total=response.total,
        line_items=list(response.line_items or []),
    )

    if response.confidence < threshold:
        reasons.append(
            f"extraction confidence {response.confidence:.2f} is below the "
            f"{threshold:.2f} auto-accept threshold"
        )

    for name in REQUIRED_FOR_ACCEPTANCE:
        if getattr(result, name) in (None, ""):
            reasons.append(f"missing {FIELD_LABELS[name]}")

    arithmetic_problems = _check_arithmetic(result.as_field_dict())
    if arithmetic_problems:
        reasons.extend(arithmetic_problems)
        # Withhold the impossible figure instead of writing it to the ledger.
        # The value the service claimed stays visible in raw_extraction.
        reasons.append("total withheld from the record until a reviewer confirms it")
        result.total = None

    if result.total is not None and result.total <= 0:
        reasons.append(f"total {result.total} is not a positive amount")

    if result.line_items and result.subtotal is not None:
        amounts = [item.get("amount") for item in result.line_items]
        if all(amount is not None for amount in amounts):
            summed = sum((Decimal(str(a)) for a in amounts), Decimal("0.00")).quantize(TWO_PLACES)
            if summed != Decimal(result.subtotal).quantize(TWO_PLACES):
                reasons.append(
                    f"line items sum to {summed} but the subtotal states {result.subtotal}"
                )

    result.review_reasons = reasons
    return result


def blocking_reasons_for_acceptance(fields: dict[str, Any]) -> list[str]:
    """Reasons a human is not allowed to accept these figures as final.

    Used when a reviewer approves a document: approving must not be a way to
    smuggle an incomplete or inconsistent record past the checks.
    """

    problems = [
        f"missing {FIELD_LABELS[name]}"
        for name in REQUIRED_FOR_ACCEPTANCE
        if fields.get(name) in (None, "")
    ]
    problems.extend(_check_arithmetic(fields))
    total = fields.get("total")
    if total is not None and Decimal(total) <= 0:
        problems.append(f"total {total} is not a positive amount")
    return problems
