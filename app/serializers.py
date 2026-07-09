"""Model -> response object conversion."""

from app.models import Booking, RefundLog, Room
from app.timeutils import isoformat_utc


def room_to_dict(room: Room) -> dict:
    return {
        "id": room.id,
        "org_id": room.org_id,
        "name": room.name,
        "capacity": room.capacity,
        "hourly_rate_cents": room.hourly_rate_cents,
    }


def booking_to_dict(booking: Booking) -> dict:
    return {
        "id": booking.id,
        "reference_code": booking.reference_code,
        "room_id": booking.room_id,
        "user_id": booking.user_id,
        "start_time": isoformat_utc(booking.start_time),
        "end_time": isoformat_utc(booking.end_time),
        "status": booking.status,
        "price_cents": booking.price_cents,
        "created_at": isoformat_utc(booking.created_at),
    }


def refund_to_dict(refund: RefundLog) -> dict:
    return {
        "amount_cents": refund.amount_cents,
        "status": refund.status,
        "processed_at": isoformat_utc(refund.processed_at),
    }
