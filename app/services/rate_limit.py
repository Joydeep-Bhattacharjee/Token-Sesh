"""Rolling-window rate limiting for POST /bookings.

20 requests per rolling 60 seconds per user. Every request counts,
including ones later rejected by validation or business rules, so the
check runs first on the request path and records the hit unconditionally.
"""

import threading
import time
from collections import defaultdict, deque

from app import config

_lock = threading.Lock()
_hits: dict[int, deque] = defaultdict(deque)


def register_and_check(user_id: int) -> bool:
    """Record this request. True if within limit, False if rate-limited."""
    now = time.monotonic()
    window_start = now - config.BOOKING_RATE_WINDOW_SECONDS
    with _lock:
        dq = _hits[user_id]
        while dq and dq[0] <= window_start:
            dq.popleft()
        dq.append(now)
        return len(dq) <= config.BOOKING_RATE_LIMIT
