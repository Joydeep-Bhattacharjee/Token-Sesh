"""Admin routes: usage report and CSV export."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.cache import cache
from app.database import get_db
from app.errors import AppError
from app.models import Booking, Room, User
from app.services.export import bookings_to_csv
from app.timeutils import isoformat_utc, to_naive_utc

router = APIRouter(prefix="/admin")


@router.get("/usage-report")
def usage_report(
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    range_start = to_naive_utc(from_)
    range_end = to_naive_utc(to)

    key = (user.org_id, "usage-report", range_start.isoformat(), range_end.isoformat())
    cached = cache.get(key)
    if cached is not None:
        return cached

    rooms = db.query(Room).filter(Room.org_id == user.org_id).order_by(Room.id.asc()).all()
    aggregates = dict(
        (room_id, (int(count), int(revenue)))
        for room_id, count, revenue in (
            db.query(
                Booking.room_id,
                func.count(Booking.id),
                func.coalesce(func.sum(Booking.price_cents), 0),
            )
            .join(Room, Booking.room_id == Room.id)
            .filter(
                Room.org_id == user.org_id,
                Booking.status == "confirmed",
                Booking.start_time >= range_start,
                Booking.start_time <= range_end,
            )
            .group_by(Booking.room_id)
            .all()
        )
    )
    result = {
        "from": isoformat_utc(range_start),
        "to": isoformat_utc(range_end),
        "rooms": [
            {
                "room_id": room.id,
                "room_name": room.name,
                "confirmed_bookings": aggregates.get(room.id, (0, 0))[0],
                "revenue_cents": aggregates.get(room.id, (0, 0))[1],
            }
            for room in rooms
        ],
    }
    cache.set(key, result)
    return result


@router.get("/export")
def export_bookings(
    room_id: int | None = Query(None),
    include_all: bool = Query(False),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    query = (
        db.query(Booking)
        .join(Room, Booking.room_id == Room.id)
        .filter(Room.org_id == user.org_id)
    )
    if room_id is not None:
        room = db.query(Room).filter(Room.id == room_id, Room.org_id == user.org_id).first()
        if room is None:
            raise AppError(404, "ROOM_NOT_FOUND", "Room not found")
        query = query.filter(Booking.room_id == room.id)
    if not include_all:
        query = query.filter(Booking.status == "confirmed")

    bookings = query.order_by(Booking.id.asc()).all()
    csv_text = bookings_to_csv(bookings)
    return Response(content=csv_text, media_type="text/csv")
