"""SQLAlchemy database models."""

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base
from app.timeutils import now_utc_naive


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True, index=True)

    users = relationship("User", back_populates="org")
    rooms = relationship("Room", back_populates="org")


class User(Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("org_id", "username", name="uq_users_org_username"),)

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    username = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)  # admin | member
    created_at = Column(DateTime, nullable=False, default=now_utc_naive)

    org = relationship("Organization", back_populates="users")


class Room(Base):
    __tablename__ = "rooms"

    id = Column(Integer, primary_key=True)
    org_id = Column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    name = Column(String, nullable=False)
    capacity = Column(Integer, nullable=False, default=1)
    hourly_rate_cents = Column(Integer, nullable=False)

    org = relationship("Organization", back_populates="rooms")


class Booking(Base):
    __tablename__ = "bookings"

    id = Column(Integer, primary_key=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    start_time = Column(DateTime, nullable=False, index=True)  # naive UTC
    end_time = Column(DateTime, nullable=False)                # naive UTC
    status = Column(String, nullable=False, default="confirmed")  # confirmed | cancelled
    reference_code = Column(String, nullable=False, unique=True, index=True)
    price_cents = Column(Integer, nullable=False)
    created_at = Column(DateTime, nullable=False, default=now_utc_naive)

    room = relationship("Room")
    user = relationship("User")
    refunds = relationship("RefundLog", back_populates="booking")


class RefundLog(Base):
    __tablename__ = "refund_logs"

    id = Column(Integer, primary_key=True)
    booking_id = Column(Integer, ForeignKey("bookings.id"), nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="processed")  # processed | failed
    processed_at = Column(DateTime, nullable=False, default=now_utc_naive)

    booking = relationship("Booking", back_populates="refunds")
