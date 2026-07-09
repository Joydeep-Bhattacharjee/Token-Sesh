"""Bookings CSV export.

Header is contract-exact:
id,reference_code,room_id,user_id,start_time,end_time,status,price_cents
"""

import csv
import io

from app.models import Booking
from app.timeutils import isoformat_utc

CSV_HEADER = [
    "id",
    "reference_code",
    "room_id",
    "user_id",
    "start_time",
    "end_time",
    "status",
    "price_cents",
]


def bookings_to_csv(bookings: list[Booking]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for b in bookings:
        writer.writerow([
            b.id,
            b.reference_code,
            b.room_id,
            b.user_id,
            isoformat_utc(b.start_time),
            isoformat_utc(b.end_time),
            b.status,
            b.price_cents,
        ])
    return buf.getvalue()
