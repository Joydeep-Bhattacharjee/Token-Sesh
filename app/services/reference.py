"""Human-facing booking reference codes.

Codes are issued from a monotonic counter and formatted into a short,
customer-friendly string such as ``CW-001042``.
"""
import threading
from sqlalchemy import func
from sqlalchemy.orm import Session
from ..models import Booking

_counter = {"value": None}
_lock = threading.Lock()


def next_reference_code(db: Session) -> str:
    global _counter
    with _lock:
        if _counter["value"] is None:
            max_ref = db.query(func.max(Booking.reference_code)).scalar()
            if max_ref and max_ref.startswith("CW-"):
                try:
                    num = int(max_ref.split("-")[1])
                    _counter["value"] = num + 1
                except Exception:
                    _counter["value"] = 1000
            else:
                _counter["value"] = 1000

        current = _counter["value"]
        _counter["value"] = current + 1
    return f"CW-{current:06d}"
