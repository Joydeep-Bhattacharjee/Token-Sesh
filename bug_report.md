# Bug Report

This document details all bugs discovered and fixed in the CoWork codebase, mapped against the business rules described in the problem statement.

### 1. Naive UTC Conversion Ignored Offsets
* **File:** `app/timeutils.py`
* **What:** The `parse_input_datetime` function stripped the `tzinfo` from inputs without converting them to UTC first if an offset was provided. For example, an input like `2026-07-09T20:00:00+06:00` would be improperly saved as `2026-07-09 20:00:00` in UTC instead of `14:00:00`.
* **Fix:** Replaced `dt.replace(tzinfo=None)` with `dt.astimezone(timezone.utc).replace(tzinfo=None)` to enforce correct UTC normalization.

### 2. Float Math Caused Incorrect Refund Rounding
* **File:** `app/services/refunds.py`
* **What:** Calculating the refund by converting to floats and casting to `int()` (e.g. `int(refund_dollars * 100)`) caused downward truncation, violating the rule "rounds to the nearest cent, half-cents rounding up."
* **Fix:** Transitioned to the `decimal` module using `ROUND_HALF_UP` to precisely calculate and quantize the refund percentage.

### 3. Non-Thread-Safe Reference Code Issuance
* **File:** `app/services/reference.py`
* **What:** `_counter` incremented in an unprotected read-modify-write pattern coupled with an artificial delay (`_format_pause()`), guaranteeing duplicate reference codes under concurrent requests.
* **Fix:** Introduced a `threading.Lock()` to serialize issuance and fetched the max existing code from the database on startup.

### 4. Non-Thread-Safe Rate Limiter
* **File:** `app/services/ratelimit.py`
* **What:** Bucket pruning and appending were executed outside of any lock with an artificial `_settle_pause()`, opening a race condition where concurrent requests could bypass the 20-request limit.
* **Fix:** Wrapped the bucket update and counting logic cleanly inside a `threading.Lock()`.

### 5. Double Booking and Quota Validation Race Conditions
* **File:** `app/routers/bookings.py`
* **What:** `create_booking` checked for double bookings (`_has_conflict`) and quota limits (`_check_quota`) without synchronization, meaning concurrent requests could over-book a room or exceed the 3-booking window quota.
* **Fix:** Enclosed the conflict validation, quota validation, and `db.add(booking)` database insertion strictly inside `with _booking_lock:`.

### 6. Eventual Consistency Drift in Room Statistics
* **File:** `app/services/stats.py` & `app/routers/rooms.py`
* **What:** Room stats were manually incremented/decremented in an in-memory dictionary `_stats` subject to race conditions and artificial delays (`_aggregate_pause()`), violating the requirement that stats "always equal the values derivable from the bookings themselves."
* **Fix:** Discarded the manual tracker and refactored `get()` to calculate aggregate statistics securely from the database using `db.query(func.count, func.sum)` dynamically.

### 7. Export Feature Multi-Tenancy Data Leak
* **File:** `app/services/export.py`
* **What:** When `include_all` was set, the `generate_export` function bypassed `_fetch_scoped` and instead invoked a `fetch_bookings_raw` fallback, completely ignoring the `org_id` multi-tenancy rules and leaking data.
* **Fix:** Streamlined the export to strictly use `_fetch_scoped(db, org_id, room_id, include_all)`.

### 8. Cross-Org Isolation Bypass in Export Endpoint
* **File:** `app/routers/admin.py`
* **What:** The `GET /admin/export` endpoint optionally accepted a `room_id`, but failed to verify if that `room_id` belonged to the caller's organization. An external `room_id` returned an empty CSV (HTTP 200) instead of correctly throwing `404 ROOM_NOT_FOUND`.
* **Fix:** Inserted an explicit database check to assert `Room.org_id == admin.org_id` before allowing the export to proceed.

### 9. Cache Invalidation Failures
* **File:** `app/routers/bookings.py`
* **What:** `create_booking` updated the DB but failed to invalidate the admin usage report cache. Inversely, `cancel_booking` failed to invalidate the room's availability cache. This led to stale, inconsistent views of current capacity.
* **Fix:** Added `cache.invalidate_report(user.org_id)` during booking creation and `cache.invalidate_availability(room.id, booking.start_time.date().isoformat())` during booking cancellation.

### 10. Start Time Overwritten in Details Response
* **File:** `app/routers/bookings.py` (Line 171)
* **What:** The `GET /bookings/{booking_id}` endpoint accidentally overwrote the serialized `start_time` value with the `created_at` timestamp due to a stray reassignment line.
* **Fix:** Removed the buggy assignment line (`response["start_time"] = iso_utc(booking.created_at)`).

### 11. Notification Deadlock
* **File:** `app/services/notifications.py`
* **What:** `notify_created` acquired `_email_lock` then `_audit_lock`, while `notify_cancelled` acquired `_audit_lock` then `_email_lock`. This classic out-of-order locking scheme created a fatal deadlock when concurrent creations and cancellations collided.
* **Fix:** Un-nested the locks so they are acquired independently and sequentially across both functions.
