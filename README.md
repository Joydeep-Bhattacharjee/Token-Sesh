# CoWork — Multi-Tenant Room Booking API

FastAPI + SQLAlchemy + SQLite room-booking service for the IUT 12th ICT Fest
Bdapps Agentic AI Hackathon (preliminary round).

## Run

```bash
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

SQLite database file `cowork.db` is created automatically on first start.
Interactive docs at `/docs`.

## Layout

```
app/
├── main.py          # FastAPI app entrypoint
├── config.py        # Environment/config loading
├── database.py      # Engine + session setup (WAL, busy timeout)
├── models.py        # SQLAlchemy models
├── schemas.py       # Pydantic request schemas
├── serializers.py   # Model -> response conversion
├── auth.py          # JWT (HS256), password hashing, auth dependency
├── cache.py         # In-memory cache, org-scoped invalidation
├── errors.py        # {"detail", "code"} error contract
├── timeutils.py     # UTC normalization helpers
├── routers/         # auth, rooms, bookings, admin, health
└── services/        # refunds, stats, rate limiting, reference codes, export, notifications
```

## Behavior guarantees (spec Sections 3–4)

- All datetimes normalized to UTC (offset inputs converted via `astimezone`,
  naive treated as UTC); responses carry an explicit `Z` designator.
- No double-booking, quota (3 per 24h window), and unique reference codes hold
  under concurrent requests (serialized check-and-insert + DB unique constraint).
- Cancellation is an atomic status flip (rowcount-checked): concurrent cancels
  produce exactly one winner and exactly one RefundLog.
- Refunds: 100% / 50% / 0% by notice tier, `Decimal ROUND_HALF_UP` to the cent.
- Rolling 60s/20-request rate limit on `POST /bookings`; every request counts.
- Access tokens expire in exactly 900s; logout blacklists the jti; refresh
  tokens are single-use; `type` claim enforced.
- Every query is org-scoped; cross-org IDs behave as 404.
- Reports/availability/stats are recomputed live; the cache is invalidated on
  every write in the org.

## Verification

`../harness/fr_tests.py` (black-box, HTTP only) covers all 16 business rules,
including 20-way parallel double-booking, quota, cancel, and reference-code
races: 69/69 checks pass.
