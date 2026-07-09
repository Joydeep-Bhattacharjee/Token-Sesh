"""Pydantic request schemas."""

from datetime import datetime

from pydantic import BaseModel


class RegisterRequest(BaseModel):
    org_name: str
    username: str
    password: str


class LoginRequest(BaseModel):
    org_name: str
    username: str
    password: str


class RefreshRequest(BaseModel):
    refresh_token: str


class RoomCreateRequest(BaseModel):
    name: str
    capacity: int = 1
    hourly_rate_cents: int


class BookingCreateRequest(BaseModel):
    room_id: int
    start_time: datetime
    end_time: datetime
