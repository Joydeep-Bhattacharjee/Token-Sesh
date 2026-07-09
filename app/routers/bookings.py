"""Booking routes: create, list (paginated), read, cancel."""

import threading
from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.auth import get_current_user
from app.cache import cache
from app.database import get_db
from app.errors import AppError
from app.models import Booking, RefundLog, Room, User
from app.schemas import BookingCreateRequest
from app.serializers import booking_to_dict, refund_to_dict
from app.services.notifications import send_booking_confirmation
from app.services.rate_limit import register_and_check
from app.services.refunds import refund_amount_cents, refund_percent
from app.services.reference import generate_reference_code
from app.timeutils import now_utc_naive, to_naive_utc

router = APIRouter(prefix="/bookings")

# Serializes the check-and-insert critical section (conflict + quota +
# insert) so parallel creation requests cannot slip through the TOCTOU gap.
_booking_write_lock = threading.Lock()

_REFERENCE_INSERT_ATTEMPTS = 5


@router.post("")
def create_booking(
    payload: BookingCreateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Rate limit first: every request counts, including rejected ones.
    if not register_and_check(user.id):
        raise AppError(429, "RATE_LIMITED", "Too many booking requests")

    start = to_naive_utc(payload.start_time)
    end = to_naive_utc(payload.end_time)
    now = now_utc_naive()

    duration_seconds = (end - start).total_seconds()
    is_whole_hours = duration_seconds % 3600 == 0
    hours = int(duration_seconds // 3600)
    if (
        end <= start
        or start <= now
        or not is_whole_hours
        or hours < config.MIN_BOOKING_HOURS
        or hours > config.MAX_BOOKING_HOURS
    ):
        raise AppError(400, "INVALID_BOOKING_WINDOW", "Invalid booking window")

    room = (
        db.query(Room)
        .filter(Room.id == payload.room_id, Room.org_id == user.org_id)
        .first()
    )
    if room is None:
        raise AppError(404, "ROOM_NOT_FOUND", "Room not found")

    price_cents = room.hourly_rate_cents * hours

    with _booking_write_lock:
        conflict = (
            db.query(Booking.id)
            .filter(
                Booking.room_id == room.id,
                Booking.status == "confirmed",
                Booking.start_time < end,
                Booking.end_time > start,
            )
            .first()
        )
        if conflict is not None:
            raise AppError(409, "ROOM_CONFLICT", "Room already booked for this window")

        quota_window_end = now + timedelta(hours=config.QUOTA_WINDOW_HOURS)
        if start <= quota_window_end:
            in_window = (
                db.query(func.count(Booking.id))
                .filter(
                    Booking.user_id == user.id,
                    Booking.status == "confirmed",
                    Booking.start_time > now,
                    Booking.start_time <= quota_window_end,
                )
                .scalar()
            )
            if in_window >= config.QUOTA_MAX_BOOKINGS:
                raise AppError(409, "QUOTA_EXCEEDED", "Booking quota exceeded")

        booking = None
        for _ in range(_REFERENCE_INSERT_ATTEMPTS):
            candidate = Booking(
                room_id=room.id,
                user_id=user.id,
                start_time=start,
                end_time=end,
                status="confirmed",
                reference_code=generate_reference_code(),
                price_cents=price_cents,
            )
            db.add(candidate)
            try:
                db.commit()
                booking = candidate
                break
            except IntegrityError:
                db.rollback()
        if booking is None:
            raise AppError(409, "ROOM_CONFLICT", "Could not allocate a unique reference code")

    cache.invalidate_org(user.org_id)
    send_booking_confirmation(user.username, booking.reference_code)
    return booking_to_dict(booking)


@router.get("")
def list_bookings(
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    base = db.query(Booking).filter(Booking.user_id == user.id)
    total = base.count()
    items = (
        base.order_by(Booking.start_time.asc(), Booking.id.asc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "items": [booking_to_dict(b) for b in items],
        "page": page,
        "limit": limit,
        "total": total,
    }


def _get_visible_booking(db: Session, booking_id: int, user: User) -> Booking:
    """Org-scoped lookup; members see only their own bookings."""
    query = (
        db.query(Booking)
        .join(Room, Booking.room_id == Room.id)
        .filter(Booking.id == booking_id, Room.org_id == user.org_id)
    )
    if user.role != "admin":
        query = query.filter(Booking.user_id == user.id)
    booking = query.first()
    if booking is None:
        raise AppError(404, "BOOKING_NOT_FOUND", "Booking not found")
    return booking


@router.get("/{booking_id}")
def get_booking(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = _get_visible_booking(db, booking_id, user)
    body = booking_to_dict(booking)
    body["refunds"] = [refund_to_dict(r) for r in booking.refunds]
    return body


@router.post("/{booking_id}/cancel")
def cancel_booking(
    booking_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    booking = _get_visible_booking(db, booking_id, user)
    now = now_utc_naive()

    # Atomic status flip: exactly one concurrent cancel wins (rowcount-checked).
    result = db.execute(
        update(Booking)
        .where(Booking.id == booking.id, Booking.status == "confirmed")
        .values(status="cancelled")
    )
    if result.rowcount == 0:
        db.rollback()
        raise AppError(409, "ALREADY_CANCELLED", "Booking is already cancelled")

    notice_seconds = (booking.start_time - now).total_seconds()
    percent = refund_percent(notice_seconds)
    amount = refund_amount_cents(booking.price_cents, percent)
    db.add(RefundLog(booking_id=booking.id, amount_cents=amount, status="processed"))
    db.commit()

    cache.invalidate_org(user.org_id)
    return {
        "id": booking.id,
        "status": "cancelled",
        "refund_percent": percent,
        "refund_amount_cents": amount,
    }
