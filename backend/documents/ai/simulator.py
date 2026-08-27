"""A stand-in for the AI extraction service.

The real service would be an HTTP call to a model that reads a PDF. For this
exercise it is a local function that behaves like an unreliable dependency:
it can time out, return half of the fields, disagree with itself on
arithmetic, or hand back something a human needs to look at.

Two properties matter for the rest of the system:

1. The outcome is *seeded* by (document content hash, attempt number). Running
   the same attempt twice produces byte-identical output, which is what lets
   the pipeline treat re-execution as safe. A retry uses a different seed, so
   retrying a transient failure can genuinely succeed.
2. A document can pin a specific outcome via ``forced_outcome``. Reviewers and
   tests need to reach the failure paths on demand, not by rolling dice.
"""

from __future__ import annotations

import hashlib
import random
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from django.conf import settings

TWO_PLACES = Decimal("0.01")


class SimulatedOutcome:
    SUCCESS = "success"
    LOW_CONFIDENCE = "low_confidence"
    INCOMPLETE = "incomplete"
    ARITHMETIC_MISMATCH = "arithmetic_mismatch"
    TRANSIENT_FAILURE = "transient_failure"
    PERMANENT_FAILURE = "permanent_failure"
    # Fails transiently on the first attempt, then succeeds. Reproduces the
    # "attempt 1 failed, processing retried, extraction completed" timeline.
    FLAKY = "flaky"

    RANDOM = "random"

    ALL = (
        RANDOM,
        SUCCESS,
        LOW_CONFIDENCE,
        INCOMPLETE,
        ARITHMETIC_MISMATCH,
        TRANSIENT_FAILURE,
        FLAKY,
        PERMANENT_FAILURE,
    )

    # Outcomes the weighted random picker may choose from.
    WEIGHTED = (
        SUCCESS,
        LOW_CONFIDENCE,
        INCOMPLETE,
        ARITHMETIC_MISMATCH,
        TRANSIENT_FAILURE,
        PERMANENT_FAILURE,
    )


class ExtractionError(Exception):
    """Base class for failures reported by the extraction service."""

    retryable = False

    def __init__(self, message: str, *, code: str = "") -> None:
        self.code = code or self.__class__.__name__
        super().__init__(message)


class TransientExtractionError(ExtractionError):
    """Timeouts, rate limits, 5xx: worth trying again."""

    retryable = True


class PermanentExtractionError(ExtractionError):
    """Unparseable input or a rejected document: retrying changes nothing."""

    retryable = False


@dataclass
class ExtractionResponse:
    outcome: str
    confidence: float
    vendor_name: str | None = None
    invoice_number: str | None = None
    invoice_date: date | None = None
    currency: str | None = None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    line_items: list[dict[str, Any]] = field(default_factory=list)
    service_version: str = "invoice-extract-sim/1.4.0"
    extraction_id: str = ""
    latency_ms: int = 0

    def as_raw(self) -> dict[str, Any]:
        """JSON-safe echo of the response, stored verbatim for auditing."""

        return {
            "extraction_id": self.extraction_id,
            "service_version": self.service_version,
            "simulated_outcome": self.outcome,
            "latency_ms": self.latency_ms,
            "confidence": self.confidence,
            "fields": {
                "vendor_name": self.vendor_name,
                "invoice_number": self.invoice_number,
                "invoice_date": self.invoice_date.isoformat() if self.invoice_date else None,
                "currency": self.currency,
                "subtotal": str(self.subtotal) if self.subtotal is not None else None,
                "tax": str(self.tax) if self.tax is not None else None,
                "total": str(self.total) if self.total is not None else None,
            },
            "line_items": self.line_items,
        }


# --- input parsing -----------------------------------------------------------

_AMOUNT_RE = r"([0-9][0-9,]*(?:\.[0-9]{1,2})?)"


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.replace(",", "").replace("$", "").replace("€", "").strip()
        if not value:
            return None
    try:
        return Decimal(str(value)).quantize(TWO_PLACES)
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def _to_date(value: Any) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _first(mapping: dict[str, Any], *keys: str) -> Any:
    lowered = {str(k).lower(): v for k, v in mapping.items()}
    for key in keys:
        if lowered.get(key) not in (None, ""):
            return lowered[key]
    return None


def _parse_line_items(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    items: list[dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        quantity = _to_decimal(_first(entry, "quantity", "qty", "units")) or Decimal("1.00")
        unit_price = _to_decimal(_first(entry, "unit_price", "price", "rate", "unitprice"))
        amount = _to_decimal(_first(entry, "amount", "total", "line_total"))
        if amount is None and unit_price is not None:
            amount = (quantity * unit_price).quantize(TWO_PLACES)
        if unit_price is None and amount is not None and quantity:
            unit_price = (amount / quantity).quantize(TWO_PLACES)
        items.append(
            {
                "description": str(
                    _first(entry, "description", "desc", "item", "name") or "Unspecified"
                ),
                "quantity": str(quantity),
                "unit_price": str(unit_price) if unit_price is not None else None,
                "amount": str(amount) if amount is not None else None,
            }
        )
    return items


def _baseline_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    invoice = payload
    # Tolerate a wrapper object, which is how most inboxes deliver these.
    for wrapper in ("invoice", "document", "data"):
        nested = payload.get(wrapper)
        if isinstance(nested, dict):
            invoice = nested
            break

    line_items = _parse_line_items(
        _first(invoice, "line_items", "lineitems", "items", "lines") or []
    )
    subtotal = _to_decimal(_first(invoice, "subtotal", "net", "net_total", "amount_excl_tax"))
    if subtotal is None and line_items:
        summed = sum(
            (_to_decimal(item["amount"]) or Decimal("0.00") for item in line_items),
            Decimal("0.00"),
        )
        subtotal = summed.quantize(TWO_PLACES)

    tax = _to_decimal(_first(invoice, "tax", "vat", "tax_amount", "sales_tax"))
    total = _to_decimal(_first(invoice, "total", "amount_due", "grand_total", "total_amount"))

    return {
        "vendor_name": _first(invoice, "vendor_name", "vendor", "supplier", "supplier_name", "from"),
        "invoice_number": _first(
            invoice, "invoice_number", "invoice_no", "invoice_id", "number", "reference"
        ),
        "invoice_date": _to_date(
            _first(invoice, "invoice_date", "date", "issued_on", "issue_date")
        ),
        "currency": _first(invoice, "currency", "currency_code", "ccy"),
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
        "line_items": line_items,
    }


def _baseline_from_text(text: str) -> dict[str, Any]:
    def grab(pattern: str) -> str | None:
        match = re.search(pattern, text, re.IGNORECASE)
        return match.group(1).strip() if match else None

    return {
        "vendor_name": grab(r"(?:vendor|supplier|from|billed by)\s*[:\-]\s*(.+)"),
        "invoice_number": grab(r"invoice\s*(?:number|no\.?|#|id)?\s*[:\-#]\s*([A-Za-z0-9\-/_]+)"),
        "invoice_date": _to_date(grab(r"(?:invoice\s*)?date\s*[:\-]\s*([0-9A-Za-z/\- ]+)")),
        "currency": grab(r"currency\s*[:\-]\s*([A-Za-z]{3})"),
        "subtotal": _to_decimal(grab(rf"(?:subtotal|net)\s*[:\-]?\s*[^0-9]{{0,3}}{_AMOUNT_RE}")),
        "tax": _to_decimal(grab(rf"(?:tax|vat)\s*[:\-]?\s*[^0-9]{{0,3}}{_AMOUNT_RE}")),
        "total": _to_decimal(
            grab(rf"(?:total|amount due|grand total)\s*[:\-]?\s*[^0-9]{{0,3}}{_AMOUNT_RE}")
        ),
        "line_items": [],
    }


# --- the simulated service ---------------------------------------------------


def _pick_outcome(rng: random.Random) -> str:
    weights = settings.AI_SIMULATOR["WEIGHTS"]
    population = list(SimulatedOutcome.WEIGHTED)
    chosen_weights = [max(0.0, float(weights.get(name, 0.0))) for name in population]
    if sum(chosen_weights) <= 0:
        return SimulatedOutcome.SUCCESS
    return rng.choices(population, weights=chosen_weights, k=1)[0]


def _resolve_outcome(forced_outcome: str, attempt: int, rng: random.Random) -> str:
    forced = (forced_outcome or "").strip().lower()
    if forced == SimulatedOutcome.FLAKY:
        # Fail the first attempt only.
        return SimulatedOutcome.TRANSIENT_FAILURE if attempt <= 1 else SimulatedOutcome.SUCCESS
    if forced and forced != SimulatedOutcome.RANDOM:
        return forced
    return _pick_outcome(rng)


def extract_invoice(
    *,
    raw_text: str,
    raw_payload: dict[str, Any] | None,
    seed: str,
    attempt: int,
    forced_outcome: str = "",
    sleep: bool = True,
) -> ExtractionResponse:
    """Pretend to call an AI extraction service.

    Raises ``TransientExtractionError`` or ``PermanentExtractionError`` for the
    failure outcomes; otherwise returns an ``ExtractionResponse``.
    """

    rng = random.Random(f"{seed}:{attempt}")
    outcome = _resolve_outcome(forced_outcome, attempt, rng)

    latency_ms = int(settings.AI_SIMULATOR["LATENCY_MS"])
    if sleep and latency_ms > 0:
        time.sleep(latency_ms / 1000.0)

    if outcome == SimulatedOutcome.TRANSIENT_FAILURE:
        raise TransientExtractionError(
            "extraction service returned 503 after 30s (upstream model overloaded)",
            code="upstream_unavailable",
        )
    if outcome == SimulatedOutcome.PERMANENT_FAILURE:
        raise PermanentExtractionError(
            "document could not be recognised as an invoice",
            code="unsupported_document",
        )

    baseline = (
        _baseline_from_payload(raw_payload)
        if isinstance(raw_payload, dict)
        else _baseline_from_text(raw_text)
    )

    vendor_name = baseline["vendor_name"]
    invoice_number = baseline["invoice_number"]
    invoice_date = baseline["invoice_date"] or date.today()
    currency = (baseline["currency"] or "USD")[:3].upper()
    line_items = baseline["line_items"]

    subtotal = baseline["subtotal"]
    tax = baseline["tax"]
    total = baseline["total"]

    # Fill in whatever the payload did not state, the way a model would.
    if subtotal is None and total is not None and tax is not None:
        subtotal = (total - tax).quantize(TWO_PLACES)
    if subtotal is None and total is not None:
        subtotal = (total / Decimal("1.2")).quantize(TWO_PLACES)
    if subtotal is None:
        subtotal = Decimal(f"{rng.randrange(20000, 500000) / 100:.2f}")
    if tax is None:
        tax = (subtotal * Decimal("0.20")).quantize(TWO_PLACES)
    total = (subtotal + tax).quantize(TWO_PLACES)

    if vendor_name is None:
        vendor_name = rng.choice(
            ["Northwind Supplies Ltd", "Acme Logistics", "Blue Harbour Consulting"]
        )
    if invoice_number is None:
        invoice_number = f"INV-{rng.randrange(1000, 9999)}"

    confidence = round(rng.uniform(0.90, 0.995), 4)

    if outcome == SimulatedOutcome.LOW_CONFIDENCE:
        confidence = round(rng.uniform(0.35, 0.80), 4)
    elif outcome == SimulatedOutcome.INCOMPLETE:
        confidence = round(rng.uniform(0.80, 0.95), 4)
        # The model read the page but lost fields, which is the common real
        # world case: partial data that must not be posted blindly.
        for dropped in rng.sample(["total", "vendor_name", "invoice_number"], k=1):
            if dropped == "total":
                total = None
                tax = None
            elif dropped == "vendor_name":
                vendor_name = None
            else:
                invoice_number = None
    elif outcome == SimulatedOutcome.ARITHMETIC_MISMATCH:
        confidence = round(rng.uniform(0.88, 0.97), 4)
        # Claims a total that does not equal subtotal + tax.
        total = (total + Decimal(f"{rng.randrange(101, 999) / 100:.2f}")).quantize(TWO_PLACES)

    return ExtractionResponse(
        outcome=outcome,
        confidence=confidence,
        vendor_name=str(vendor_name)[:255] if vendor_name else None,
        invoice_number=str(invoice_number)[:128] if invoice_number else None,
        invoice_date=invoice_date,
        currency=currency,
        subtotal=subtotal,
        tax=tax,
        total=total,
        line_items=line_items,
        extraction_id=str(uuid.UUID(hashlib.sha256(f"{seed}:{attempt}".encode()).hexdigest()[:32])),
        latency_ms=latency_ms,
    )
