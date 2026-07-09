"""Booking reference code generation.

Uniqueness is guaranteed by the DB unique constraint on
bookings.reference_code plus insert-retry in the booking creation path;
this generator only needs to make collisions astronomically unlikely.
"""

import uuid


def generate_reference_code() -> str:
    return f"BK-{uuid.uuid4().hex[:12].upper()}"
