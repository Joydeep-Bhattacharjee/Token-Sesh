"""Environment/config loading."""

import os

SECRET_KEY = os.getenv("COWORK_SECRET_KEY", "cowork-dev-secret-do-not-use-in-prod")
JWT_ALGORITHM = "HS256"

ACCESS_TOKEN_TTL_SECONDS = 900          # exactly 900s per spec rule 8
REFRESH_TOKEN_TTL_SECONDS = 7 * 24 * 3600  # 7 days

DATABASE_URL = os.getenv("COWORK_DATABASE_URL", "sqlite:///./cowork.db")

BOOKING_RATE_LIMIT = 20        # requests
BOOKING_RATE_WINDOW_SECONDS = 60

MIN_BOOKING_HOURS = 1
MAX_BOOKING_HOURS = 8
QUOTA_MAX_BOOKINGS = 3
QUOTA_WINDOW_HOURS = 24
