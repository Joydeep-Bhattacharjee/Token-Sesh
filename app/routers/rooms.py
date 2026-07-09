"""Room routes: list, create, availability, stats."""

from datetime import date as date_type
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_admin
from app.cache import cache
from app.database import get_db
from app.errors import AppError
from app.models import Booking, Room, User
from app.schemas import RoomCreateRequest
from app.serializers import room_to_dict
from app.services.stats import room_confirmed_stats
from app.timeutils import isoformat_utc

router = APIRouter(prefix="/rooms")


def _get_org_room(db: Session, room_id: int, org_id: int) -> Room:
    room = db.query(Room).filter(Room.id == room_id, Room.org_id == org_id).first()
    if room is None:
        raise AppError(404, "ROOM_NOT_FOUND", "Room not found")
    return room


@router.get("")
def list_rooms(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rooms = db.query(Room).filter(Room.org_id == user.org_id).order_by(Room.id.asc()).all()
    return [room_to_dict(r) for r in rooms]


@router.post("")
def create_room(
    payload: RoomCreateRequest,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    room = Room(
        org_id=user.org_id,
        name=payload.name,
        capacity=payload.capacity,
        hourly_rate_cents=payload.hourly_rate_cents,
    )
    db.add(room)
    db.commit()
    cache.invalidate_org(user.org_id)
    return room_to_dict(room)


@router.get("/{room_id}/availability")
def availability(
    room_id: int,
    date: date_type = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = _get_org_room(db, room_id, user.org_id)
    key = (user.org_id, "availability", room.id, date.isoformat())
    cached = cache.get(key)
    if cached is not None:
        return cached

    day_start = datetime(date.year, date.month, date.day)
    day_end = day_start + timedelta(days=1)
    bookings = (
        db.query(Booking)
        .filter(
            Booking.room_id == room.id,
            Booking.status == "confirmed",
            Booking.start_time >= day_start,
            Booking.start_time < day_end,
        )
        .order_by(Booking.start_time.asc(), Booking.id.asc())
        .all()
    )
    result = {
        "room_id": room.id,
        "date": date.isoformat(),
        "busy": [
            {"start_time": isoformat_utc(b.start_time), "end_time": isoformat_utc(b.end_time)}
            for b in bookings
        ],
    }
    cache.set(key, result)
    return result


@router.get("/{room_id}/stats")
def room_stats(
    room_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    room = _get_org_room(db, room_id, user.org_id)
    key = (user.org_id, "stats", room.id)
    cached = cache.get(key)
    if cached is not None:
        return cached

    count, revenue = room_confirmed_stats(db, room.id)
    result = {
        "room_id": room.id,
        "total_confirmed_bookings": count,
        "total_revenue_cents": revenue,
    }
    cache.set(key, result)
    return result
