"""Refund policy: tiered percentage by notice, ROUND_HALF_UP to the cent."""

from decimal import ROUND_HALF_UP, Decimal

SECONDS_48H = 48 * 3600
SECONDS_24H = 24 * 3600


def refund_percent(notice_seconds: float) -> int:
    if notice_seconds >= SECONDS_48H:
        return 100
    if notice_seconds >= SECONDS_24H:
        return 50
    return 0


def refund_amount_cents(price_cents: int, percent: int) -> int:
    amount = Decimal(price_cents) * Decimal(percent) / Decimal(100)
    return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
