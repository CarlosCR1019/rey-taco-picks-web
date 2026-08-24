"""Receipt OCR helpers that can never authorize a membership."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ReceiptReview:
    status: str
    detected_amount: bool
    detected_bank: bool


def classify_receipt(text: str) -> ReceiptReview:
    normalized = str(text).lower()
    return ReceiptReview(
        status="pending_review",
        detected_amount="299" in normalized,
        detected_bank="bbva" in normalized or "spei" in normalized,
    )
