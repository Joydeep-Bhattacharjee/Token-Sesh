"""CoWork black-box FR test harness (spec rules 1-16).

Usage: python fr_tests.py [--base http://127.0.0.1:8000] [--only FR3,FR5]
All datetimes generated relative to now() in UTC. Concurrency bursts use
fresh users so the 20/60s rate limit never skews non-FR5 tests.
"""

import argparse
import asyncio
import base64
import json as jsonlib
import sys
import uuid
from datetime import datetime, timedelta, timezone

import httpx

BASE = "http://127.0.0.1:8000"
RESULTS: list[tuple[str, bool, str]] = []


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.isoformat()


def check(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")


def has_utc_designator(s):
    return s.endswith("Z") or s.endswith("+00:00")


def err_code(r):
    try:
        return r.json().get("code", "")
    except Exception:
        return ""


def jwt_claims(tok):
    p = tok.split(".")[1]
    p += "=" * (-len(p) % 4)
    return jsonlib.loads(base64.urlsafe_b64decode(p))


class Sess:
    def __init__(self, client, org, username, access, refresh, reg_body):
        self.client, self.org, self.username = client, org, username
        self.access, self.refresh, self.reg_body = access, refresh, reg_body

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.access}"}


async def register(client, org, username=None, password="pass1234"):
    username = username or f"u{uuid.uuid4().hex[:10]}"
    r = await client.post("/auth/register", json={
        "org_name": org, "username": username, "password": password})
    if r.status_code not in (200, 201):
        return r, None
    lr = await client.post("/auth/login", json={
        "org_name": org, "username": username, "password": password})
    lb = lr.json()
    return r, Sess(client, org, username, lb["access_token"], lb["refresh_token"], r.json())


async def make_admin_with_room(client, rate_cents=1000):
    org = f"org-{uuid.uuid4().hex[:8]}"
    _, admin = await register(client, org)
    rr = await client.post("/rooms", headers=admin.headers, json={
        "name": f"room-{uuid.uuid4().hex[:6]}", "capacity": 4,
        "hourly_rate_cents": rate_cents})
    assert rr.status_code in (200, 201), f"room create: {rr.status_code} {rr.text}"
    return admin, rr.json()["id"]


async def book(sess, room_id, start, end):
    return await sess.client.post("/bookings", headers=sess.headers, json={
        "room_id": room_id, "start_time": iso(start), "end_time": iso(end)})


async def cancel(sess, bid):
    return await sess.client.post(f"/bookings/{bid}/cancel", headers=sess.headers)


def slot(hours_out, dur=1):
    s = (now_utc() + timedelta(hours=hours_out)).replace(minute=0, second=0, microsecond=0)
    return s, s + timedelta(hours=dur)


# ---------------------------------------------------------------- tests
async def fr1(client):
    admin, room = await make_admin_with_room(client)
    local = (now_utc() + timedelta(hours=50)).astimezone(timezone(timedelta(hours=6)))
    local = local.replace(minute=0, second=0, microsecond=0)
    r = await book(admin, room, local, local + timedelta(hours=1))
    check("FR1 offset input accepted", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
    if r.status_code == 200:
        st = r.json()["start_time"]
        check("FR1 UTC designator", has_utc_designator(st), st)
        got = datetime.fromisoformat(st.replace("Z", "+00:00"))
        check("FR1 offset converted", got == local.astimezone(timezone.utc), st)


async def fr2(client):
    admin, room = await make_admin_with_room(client, 1234)
    s, e = slot(40, 3)
    r = await book(admin, room, s, e)
    check("FR2 price=rate*hours", r.status_code == 200 and r.json()["price_cents"] == 3702,
          f"{r.status_code} {r.text[:80]}")
    s, e = slot(60, 9)
    r = await book(admin, room, s, e)
    check("FR2 9h -> 400 INVALID_BOOKING_WINDOW",
          r.status_code == 400 and err_code(r) == "INVALID_BOOKING_WINDOW",
          f"{r.status_code} {err_code(r)}")
    s0 = slot(70)[0]
    r = await book(admin, room, s0, s0 + timedelta(minutes=90))
    check("FR2 90min -> 400", r.status_code == 400, str(r.status_code))
    r = await book(admin, room, s0, s0)
    check("FR2 end==start -> 400", r.status_code == 400, str(r.status_code))
    ps = now_utc() - timedelta(minutes=1)
    r = await book(admin, room, ps, ps + timedelta(hours=1))
    check("FR2 past start -> 400", r.status_code == 400, f"{r.status_code} {err_code(r)}")


async def fr3(client):
    admin, room = await make_admin_with_room(client)
    s, e = slot(80, 2)
    r1 = await book(admin, room, s, e)
    check("FR3 first ok", r1.status_code == 200, str(r1.status_code))
    r2 = await book(admin, room, s, e)
    check("FR3 overlap -> 409 ROOM_CONFLICT",
          r2.status_code == 409 and err_code(r2) == "ROOM_CONFLICT",
          f"{r2.status_code} {err_code(r2)}")
    r3 = await book(admin, room, e, e + timedelta(hours=1))
    check("FR3 back-to-back ok", r3.status_code == 200, f"{r3.status_code} {err_code(r3)}")
    # concurrent same slot, 20 fresh users
    users = []
    for _ in range(20):
        _, u = await register(client, admin.org)
        users.append(u)
    s2, e2 = slot(90)
    rs = await asyncio.gather(*[book(u, room, s2, e2) for u in users])
    wins = sum(1 for r in rs if r.status_code == 200)
    check("FR3 concurrent 20x: 1 winner", wins == 1, f"winners={wins}")


async def fr4(client):
    admin, room = await make_admin_with_room(client)
    _, m = await register(client, admin.org)
    base = now_utc().replace(minute=0, second=0, microsecond=0) + timedelta(hours=2)
    for i in range(3):
        s = base + timedelta(hours=i * 2)
        r = await book(m, room, s, s + timedelta(hours=1))
        check(f"FR4 in-window {i+1} ok", r.status_code == 200, f"{r.status_code} {err_code(r)}")
    s = base + timedelta(hours=8)
    r = await book(m, room, s, s + timedelta(hours=1))
    check("FR4 4th -> 409 QUOTA_EXCEEDED",
          r.status_code == 409 and err_code(r) == "QUOTA_EXCEEDED",
          f"{r.status_code} {err_code(r)}")
    s, e = slot(30)
    r = await book(m, room, s, e)
    check("FR4 >24h exempt", r.status_code == 200, f"{r.status_code} {err_code(r)}")
    # concurrent: fresh member, 10 parallel distinct in-window slots
    _, m2 = await register(client, admin.org)
    base2 = base + timedelta(hours=10)
    rs = await asyncio.gather(*[
        book(m2, room, base2 + timedelta(hours=i), base2 + timedelta(hours=i, minutes=60))
        for i in range(10)])
    wins = sum(1 for r in rs if r.status_code == 200)
    check("FR4 concurrent: <=3 winners", wins <= 3, f"winners={wins}")


async def fr5(client):
    admin, room = await make_admin_with_room(client)
    _, m = await register(client, admin.org)
    ps = now_utc() - timedelta(hours=1)
    codes = []
    for _ in range(21):
        r = await book(m, room, ps, ps + timedelta(hours=1))
        codes.append(r.status_code)
    check("FR5 first 20 not 429", all(c != 429 for c in codes[:20]), str(codes[:20]))
    check("FR5 21st -> 429 RATE_LIMITED", codes[20] == 429, f"21st={codes[20]}")


async def fr6(client):
    admin, room = await make_admin_with_room(client, 1111)
    _, m = await register(client, admin.org)
    s, e = slot(50, 3)  # price 3333
    bid = (await book(m, room, s, e)).json()["id"]
    cr = await cancel(m, bid)
    b = cr.json()
    check("FR6 >=48h -> 100%", cr.status_code == 200 and b.get("refund_amount_cents") == 3333
          and b.get("refund_percent") == 100, f"{cr.status_code} {cr.text[:120]}")
    cr2 = await cancel(m, bid)
    check("FR6 re-cancel -> 409 ALREADY_CANCELLED",
          cr2.status_code == 409 and err_code(cr2) == "ALREADY_CANCELLED",
          f"{cr2.status_code} {err_code(cr2)}")
    s = (now_utc() + timedelta(hours=30)).replace(minute=0, second=0, microsecond=0)
    bid = (await book(m, room, s, s + timedelta(hours=1))).json()["id"]
    got = (await cancel(m, bid)).json().get("refund_amount_cents")
    check("FR6 50% ROUND_HALF_UP 1111->556", got == 556, f"got {got}")
    s = (now_utc() + timedelta(hours=2)).replace(minute=0, second=0, microsecond=0)
    bid = (await book(m, room, s, s + timedelta(hours=1))).json()["id"]
    got = (await cancel(m, bid)).json().get("refund_amount_cents")
    check("FR6 <24h -> 0", got == 0, f"got {got}")
    # refund logged once, response == log
    s, e = slot(55)
    bid = (await book(m, room, s, e)).json()["id"]
    amt = (await cancel(m, bid)).json().get("refund_amount_cents")
    gr = await m.client.get(f"/bookings/{bid}", headers=m.headers)
    refunds = gr.json().get("refunds", [])
    check("FR6 exactly one RefundLog, amount matches",
          len(refunds) == 1 and refunds[0].get("amount_cents") == amt,
          f"{len(refunds)} logs, {refunds[:2]}")
    # concurrent cancel: 20 parallel, one winner
    s, e = slot(58)
    bid = (await book(m, room, s, e)).json()["id"]
    rs = await asyncio.gather(*[cancel(m, bid) for _ in range(20)])
    wins = sum(1 for x in rs if x.status_code == 200)
    check("FR6 concurrent cancel: 1 winner", wins == 1, f"winners={wins}")
    gr = await m.client.get(f"/bookings/{bid}", headers=m.headers)
    check("FR6 concurrent cancel: 1 RefundLog", len(gr.json().get("refunds", [])) == 1,
          str(len(gr.json().get("refunds", []))))


async def fr7(client):
    admin, room = await make_admin_with_room(client)
    members = []
    for _ in range(6):
        _, u = await register(client, admin.org)
        members.append(u)
    base = now_utc().replace(minute=0, second=0, microsecond=0) + timedelta(hours=100)
    tasks, i = [], 0
    for u in members:
        for _ in range(3):
            s = base + timedelta(hours=i)
            tasks.append(book(u, room, s, s + timedelta(hours=1)))
            i += 1
    rs = await asyncio.gather(*tasks)
    ok = [r for r in rs if r.status_code == 200]
    refs = {r.json()["reference_code"] for r in ok}
    check("FR7 unique refs under concurrency (18 parallel)",
          len(ok) == 18 and len(refs) == 18, f"{len(ok)} ok, {len(refs)} unique")


async def fr8(client):
    org = f"org-{uuid.uuid4().hex[:8]}"
    _, u = await register(client, org)
    c = jwt_claims(u.access)
    check("FR8 exp-iat==900", c["exp"] - c["iat"] == 900, str(c["exp"] - c["iat"]))
    check("FR8 claims complete",
          all(k in c for k in ("sub", "org", "role", "jti", "iat", "exp", "type")),
          str(sorted(c)))
    check("FR8 sub is string", isinstance(c["sub"], str), str(type(c["sub"])))
    rc = jwt_claims(u.refresh)
    check("FR8 refresh exp 7d", rc["exp"] - rc["iat"] == 7 * 86400, str(rc["exp"] - rc["iat"]))
    r = await client.get("/bookings", headers={"Authorization": f"Bearer {u.refresh}"})
    check("FR8 refresh token rejected as access", r.status_code == 401, str(r.status_code))
    r1 = await client.post("/auth/refresh", json={"refresh_token": u.refresh})
    check("FR8 refresh rotates", r1.status_code == 200, str(r1.status_code))
    r2 = await client.post("/auth/refresh", json={"refresh_token": u.refresh})
    check("FR8 refresh reuse -> 401", r2.status_code == 401, str(r2.status_code))
    lo = await client.post("/auth/logout", headers=u.headers)
    check("FR8 logout ok", lo.status_code in (200, 204), str(lo.status_code))
    r = await client.get("/bookings", headers=u.headers)
    check("FR8 access dead after logout", r.status_code == 401, str(r.status_code))
    new_access = r1.json()["access_token"]
    r = await client.get("/bookings", headers={"Authorization": f"Bearer {new_access}"})
    check("FR8 rotated access works", r.status_code == 200, str(r.status_code))


async def fr9_10(client):
    a1, room1 = await make_admin_with_room(client)
    a2, room2 = await make_admin_with_room(client)
    s, e = slot(120)
    bid = (await book(a1, room1, s, e)).json()["id"]
    r = await client.get(f"/bookings/{bid}", headers=a2.headers)
    check("FR9 cross-org booking -> 404", r.status_code == 404, str(r.status_code))
    r = await book(a2, room1, *slot(125))
    check("FR9 cross-org room -> 404", r.status_code == 404, f"{r.status_code} {err_code(r)}")
    r = await client.get(f"/rooms/{room1}/stats", headers=a2.headers)
    check("FR9 cross-org stats -> 404", r.status_code == 404, str(r.status_code))
    _, m1 = await register(client, a1.org)
    _, m2 = await register(client, a1.org)
    s, e = slot(130)
    bid = (await book(m1, room1, s, e)).json()["id"]
    r = await client.get(f"/bookings/{bid}", headers=m2.headers)
    check("FR10 foreign member booking -> 404 BOOKING_NOT_FOUND",
          r.status_code == 404 and err_code(r) == "BOOKING_NOT_FOUND",
          f"{r.status_code} {err_code(r)}")
    r = await cancel(m2, bid)
    check("FR10 foreign member cancel -> 404", r.status_code == 404, str(r.status_code))
    r = await client.get(f"/bookings/{bid}", headers=a1.headers)
    check("FR10 admin reads org booking", r.status_code == 200, str(r.status_code))
    r = await cancel(a1, bid)
    check("FR10 admin cancels org booking", r.status_code == 200, str(r.status_code))
    # member hitting admin endpoint -> 403
    r = await client.get("/admin/usage-report", headers=m1.headers,
                         params={"from": iso(s), "to": iso(e)})
    check("FR10 member on admin endpoint -> 403", r.status_code == 403,
          f"{r.status_code} {err_code(r)}")


async def fr11(client):
    admin, room = await make_admin_with_room(client)
    base = now_utc().replace(minute=0, second=0, microsecond=0) + timedelta(hours=200)
    for i in range(15):
        s = base + timedelta(hours=i)
        r = await book(admin, room, s, s + timedelta(hours=1))
        assert r.status_code == 200, r.text
    r1 = (await client.get("/bookings", headers=admin.headers,
                           params={"page": 1, "limit": 10})).json()
    r2 = (await client.get("/bookings", headers=admin.headers,
                           params={"page": 2, "limit": 10})).json()
    check("FR11 total==15", r1.get("total") == 15, str(r1.get("total")))
    check("FR11 sizes 10/5", len(r1["items"]) == 10 and len(r2["items"]) == 5,
          f"{len(r1['items'])}/{len(r2['items'])}")
    allb = r1["items"] + r2["items"]
    check("FR11 no skip/repeat", len({b['id'] for b in allb}) == 15, "")
    starts = [b["start_time"] for b in allb]
    check("FR11 start ASC", starts == sorted(starts), "")
    rd = (await client.get("/bookings", headers=admin.headers)).json()
    check("FR11 defaults page1 limit10", rd["page"] == 1 and rd["limit"] == 10
          and len(rd["items"]) == 10, "")


async def fr12(client):
    admin, room = await make_admin_with_room(client, 500)
    rr = await client.post("/rooms", headers=admin.headers,
                           json={"name": "empty", "capacity": 2, "hourly_rate_cents": 700})
    room2 = rr.json()["id"]
    s, e = slot(240, 2)  # price 1000
    bid = (await book(admin, room, s, e)).json()["id"]
    frm, to = iso(s - timedelta(hours=1)), iso(s + timedelta(hours=1))
    r = await client.get("/admin/usage-report", headers=admin.headers,
                         params={"from": frm, "to": to})
    check("FR12 report 200", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
    body = r.json()
    by_room = {x["room_id"]: x for x in body.get("rooms", [])}
    check("FR12 zero-booking room present", room2 in by_room, str(list(by_room)))
    row = by_room.get(room, {})
    check("FR12 count/revenue", row.get("confirmed_bookings") == 1
          and row.get("revenue_cents") == 1000, str(row))
    # boundary inclusive: from == start
    r = await client.get("/admin/usage-report", headers=admin.headers,
                         params={"from": iso(s), "to": iso(s)})
    row = {x["room_id"]: x for x in r.json()["rooms"]}.get(room, {})
    check("FR12 [from,to] inclusive", row.get("confirmed_bookings") == 1, str(row))
    # live after cancel
    await cancel(admin, bid)
    r = await client.get("/admin/usage-report", headers=admin.headers,
                         params={"from": frm, "to": to})
    row = {x["room_id"]: x for x in r.json()["rooms"]}.get(room, {})
    check("FR12 live after cancel", row.get("confirmed_bookings") == 0, str(row))
    # export CSV
    r = await client.get("/admin/export", headers=admin.headers)
    header = r.text.splitlines()[0] if r.text else ""
    check("FR12 CSV header exact",
          header == "id,reference_code,room_id,user_id,start_time,end_time,status,price_cents",
          header)


async def fr13(client):
    admin, room = await make_admin_with_room(client)
    s, e = slot(75, 2)
    await book(admin, room, s, e)
    s2 = s.replace(hour=(s.hour + 3) % 24)
    date_str = s.date().isoformat()
    r = await client.get(f"/rooms/{room}/availability", headers=admin.headers,
                         params={"date": date_str})
    check("FR13 availability 200", r.status_code == 200, f"{r.status_code} {r.text[:100]}")
    body = r.json()
    busy = body.get("busy", [])
    match = [i for i in busy if i["start_time"].startswith(date_str)]
    check("FR13 booking listed for its UTC date", len(match) >= 1, str(busy)[:120])
    starts = [i["start_time"] for i in busy]
    check("FR13 sorted asc", starts == sorted(starts), "")
    # live: cancel then re-query
    bid_r = await book(admin, room, e, e + timedelta(hours=1))
    bid = bid_r.json()["id"]
    await cancel(admin, bid)
    r = await client.get(f"/rooms/{room}/availability", headers=admin.headers,
                         params={"date": date_str})
    busy2 = r.json().get("busy", [])
    check("FR13 live after cancel", len(busy2) == len(busy), f"{len(busy)}->{len(busy2)}")


async def fr14(client):
    admin, room = await make_admin_with_room(client, 200)
    _, m = await register(client, admin.org)
    base = now_utc().replace(minute=0, second=0, microsecond=0) + timedelta(hours=300)
    rs = await asyncio.gather(*[
        book(m, room, base + timedelta(hours=i), base + timedelta(hours=i, minutes=60))
        for i in range(20)])
    made = sum(1 for r in rs if r.status_code == 200)
    r = await client.get(f"/rooms/{room}/stats", headers=admin.headers)
    b = r.json()
    check("FR14 stats live == table after burst",
          b.get("total_confirmed_bookings") == made
          and b.get("total_revenue_cents") == made * 200,
          f"stats={b} made={made}")


async def fr15(client):
    org = f"org-{uuid.uuid4().hex[:8]}"
    r1, _ = await register(client, org, username="alice")
    check("FR15 new org -> admin", r1.json().get("role") == "admin", r1.text[:80])
    r2, _ = await register(client, org, username="bob")
    check("FR15 known org -> member", r2.json().get("role") == "member", r2.text[:80])
    r3 = await client.post("/auth/register", json={
        "org_name": org, "username": "alice", "password": "x12345678"})
    check("FR15 dup username -> 409 USERNAME_TAKEN",
          r3.status_code == 409 and err_code(r3) == "USERNAME_TAKEN",
          f"{r3.status_code} {err_code(r3)}")
    org2 = f"org-{uuid.uuid4().hex[:8]}"
    r4, _ = await register(client, org2, username="alice")
    check("FR15 same username other org ok", r4.status_code == 200, str(r4.status_code))
    # bad login
    r = await client.post("/auth/login", json={
        "org_name": org, "username": "alice", "password": "wrong"})
    check("FR15 bad creds -> 401 INVALID_CREDENTIALS",
          r.status_code == 401 and err_code(r) == "INVALID_CREDENTIALS",
          f"{r.status_code} {err_code(r)}")
    r = await client.get("/health")
    check("FR15 health", r.status_code == 200 and r.json() == {"status": "ok"}, r.text[:40])


async def fr16(client):
    admin, room = await make_admin_with_room(client)
    users = []
    for _ in range(6):
        _, u = await register(client, admin.org)
        users.append(u)
    base = now_utc().replace(minute=0, second=0, microsecond=0) + timedelta(hours=400)
    tasks = []
    for k in range(30):
        u = users[k % 6]
        s = base + timedelta(hours=k % 10)
        tasks.append(book(u, room, s, s + timedelta(hours=1)))
        tasks.append(client.get("/bookings", headers=u.headers))
        tasks.append(client.get(f"/rooms/{room}/stats", headers=u.headers))
    try:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=45)
        check("FR16 no hang under 90 mixed concurrent requests", True, "")
    except asyncio.TimeoutError:
        check("FR16 no hang under 90 mixed concurrent requests", False, "TIMEOUT")


ALL = {f.__name__.upper().replace("_", "-"): f for f in [
    fr1, fr2, fr3, fr4, fr5, fr6, fr7, fr8, fr9_10, fr11, fr12, fr13, fr14, fr15, fr16]}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE)
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    picks = [p.strip().upper() for p in args.only.split(",") if p.strip()] or list(ALL)
    limits = httpx.Limits(max_connections=100)
    async with httpx.AsyncClient(base_url=args.base, timeout=60, limits=limits) as client:
        for name in picks:
            fn = ALL.get(name)
            if fn is None:
                print(f"[skip] {name}")
                continue
            print(f"\n=== {name} ===")
            try:
                await fn(client)
            except Exception as ex:
                check(f"{name} harness error", False, f"{type(ex).__name__}: {ex}")
    failed = [x for x in RESULTS if not x[1]]
    print(f"\n{'='*52}\n{len(RESULTS) - len(failed)}/{len(RESULTS)} passed, {len(failed)} failed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
