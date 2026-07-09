"""Room statistics recomputed live from the bookings table (source of truth)."""

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Booking


def room_confirmed_stats(db: Session, room_id: int) -> tuple[int, int]:
    """Return (confirmed booking count, summed price_cents) for a room."""
    count, revenue = (
        db.query(func.count(Booking.id), func.coalesce(func.sum(Booking.price_cents), 0))
        .filter(Booking.room_id == room_id, Booking.status == "confirmed")
        .one()
    )
    return int(count), int(revenue)
