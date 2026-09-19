"""Receipt OCR helpers that can never authorize a membership."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReceiptReview:
    status: str
    detected_amount: bool
    detected_bank: bool
    detected_plan: str | None = None


def classify_receipt(text: str) -> ReceiptReview:
    normalized = str(text).lower()
    plan = None
    if "129" in normalized:
        plan = "weekly"
    elif "349" in normalized:
        plan = "monthly"
    elif "299" in normalized:
        plan = "legacy_monthly"

    return ReceiptReview(
        status="pending_review",
        detected_amount=plan is not None,
        detected_bank="bbva" in normalized or "spei" in normalized,
        detected_plan=plan,
    )

