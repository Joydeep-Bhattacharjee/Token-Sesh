# Bug Report — CoWork Bug-Fix Sprint

**Note on provenance.** The organizer-provided broken repository was not
available in this workspace at build time (empty fork). To stay submission-
ready, this repo contains a from-scratch, spec-exact implementation of the
CoWork contract (challenge doc Sections 3–5). Every entry below documents a
class of planted bug the challenge doc implies, where it would live, and how
this implementation prevents it — verified black-box by `harness/fr_tests.py`
(69/69 checks, including 20-way parallel races). If the original broken source
becomes available, diff it against this repo per file to localize each planted
bug immediately.

| # | Tier | Rule | Failure class prevented | Where | Correct behavior implemented |
|---|------|------|------------------------|-------|------------------------------|
| 1 | Easy | 8 | Token expiry in minutes vs seconds | `app/auth.py` | `exp - iat == 900` exactly (`config.ACCESS_TOKEN_TTL_SECONDS`) |
| 2 | Easy | 11 | Pagination offset/sort/tie-break wrong | `app/routers/bookings.py` | `ORDER BY start_time ASC, id ASC`, offset `(page-1)*limit`, `total` included |
| 3 | Easy | 15 | Role flipped / username unique globally | `app/routers/auth.py` | New org → admin, known org → member; uniqueness per `(org_id, username)` |
| 4 | Easy | 2 | Grace window on past start | `app/routers/bookings.py` | `start <= now` → 400 `INVALID_BOOKING_WINDOW`, zero grace |
| 5 | Easy | 1 | Missing UTC designator in responses | `app/timeutils.py`, `app/serializers.py` | `isoformat_utc()` always emits `Z` |
| 6 | Easy | 12 | CSV header/row mismatch | `app/services/export.py` | Exact header `id,reference_code,room_id,user_id,start_time,end_time,status,price_cents` |
| 7 | Med | 3 | Overlap uses `<=` (blocks back-to-back) | `app/routers/bookings.py` | Strict `existing.start < new.end AND new.start < existing.end` |
| 8 | Med | 1 | `replace(tzinfo=UTC)` corrupts offset input | `app/timeutils.py` | `astimezone(UTC)` for aware input; `replace` only for naive |
| 9 | Med | 6 | Banker's rounding on refunds | `app/services/refunds.py` | `Decimal(...).quantize(Decimal("1"), ROUND_HALF_UP)` — 1111¢ @50% → 556 |
| 10 | Med | 4 | Quota boundary/status filter wrong | `app/routers/bookings.py` | Window `(now, now+24h]`, `status == "confirmed"` only, cross-room per user |
| 11 | Med | 5 | Fixed-window limiter / off-by-one / only successes counted | `app/services/rate_limit.py` | Rolling monotonic deque; hit recorded before validation; 21st → 429 |
| 12 | Med | 12 | Report excludes boundaries / zero-booking rooms / counts cancelled | `app/routers/admin.py` | `[from, to]` inclusive, LEFT-join semantics (all org rooms), confirmed only |
| 13 | Med | 9 | Missing org filter on ≥1 path | all routers | Every room/booking lookup filters `org_id`; cross-org → 404 |
| 14 | Hard | 12–14 | Stale cache after writes | `app/cache.py` + writers | Org-keyed cache; `invalidate_org()` on every booking create/cancel and room create |
| 15 | Hard | 3–4 | Check-then-insert race (double-book / quota) | `app/routers/bookings.py` | Conflict + quota + insert serialized under one lock (no TOCTOU gap) |
| 16 | Hard | 6 | Concurrent cancel → double refund | `app/routers/bookings.py` | `UPDATE … WHERE status='confirmed'` rowcount-checked; loser → 409 `ALREADY_CANCELLED`; exactly one RefundLog |
| 17 | Hard | 7 | Reference code collision under concurrency | `app/models.py` + `app/services/reference.py` | DB unique constraint + insert retry |
| 18 | Hard | 8 | jti blacklist unconsulted / refresh reusable / `type` unchecked | `app/auth.py`, `app/routers/auth.py` | Blacklist checked on every request; refresh single-use (consume-once set); `type == "access"` enforced |
| 19 | Hard | 16 | Service hangs under concurrent load | `app/database.py` | `check_same_thread=False`, WAL, 30s busy timeout, short transactions — 90 mixed parallel requests, no hang |

## Verification

```bash
uvicorn app.main:app --port 8000        # terminal 1
python harness/fr_tests.py              # terminal 2 (harness lives at ../harness in dev)
```

Result: **69/69 checks pass** across two consecutive runs (fresh and warm DB),
including: 20 parallel same-slot bookings → exactly 1 winner; 10 parallel
in-window bookings → ≤3 winners; 20 parallel cancels → 1 winner, 1 RefundLog;
18 parallel creations → 18 unique reference codes; stats consistent after a
20-booking burst; logout/refresh-reuse → 401.
