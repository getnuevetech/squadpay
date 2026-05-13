"""
P1 Follow-ups — backend tests
    M1 — Maintenance Mode round trip (toggle ON → 503, toggle OFF → 200)
    M2 — Maintenance only affects POST /api/groups (existing groups continue)
    P1 — Admin auth gating on POST /api/admin/users/run-purge-cron
    P2 — Functional purge for past-grace user
    P3 — Within grace user not purged
    P4 — Idempotency
    P5 — Edge case: deletion_scheduled_at = null

Run:  python /app/backend_test.py
"""
import os
import sys
import time
import json
import asyncio
from datetime import datetime, timezone, timedelta

import requests
from motor.motor_asyncio import AsyncIOMotorClient

BASE = "http://localhost:8001/api"
ADMIN_EMAIL = "admin@squadpay.us"
ADMIN_PASSWORD = "Letmein@2007#ForReal"

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "test_database")

PASS, FAIL = 0, 0
FAILS = []


def _check(label, cond, info=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        FAILS.append((label, info))
        print(f"  ❌ {label}  {info}")


def admin_login():
    r = requests.post(f"{BASE}/admin/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


def get_app_config(token):
    r = requests.get(f"{BASE}/admin/app-config", headers={"Authorization": f"Bearer {token}"}, timeout=30)
    r.raise_for_status()
    return r.json()


def put_app_config(token, cfg):
    r = requests.put(
        f"{BASE}/admin/app-config",
        headers={"Authorization": f"Bearer {token}"},
        json=cfg,
        timeout=30,
    )
    return r


def set_maintenance(token, base_cfg, on: bool, msg=None):
    cfg = json.loads(json.dumps(base_cfg))  # deep copy
    cfg.setdefault("ops", {})
    cfg["ops"]["maintenance_mode"] = on
    if msg is not None:
        cfg["ops"]["maintenance_message"] = msg
    r = put_app_config(token, cfg)
    r.raise_for_status()
    return r.json()


def find_active_user(token):
    """Get a real, non-deleted, non-blocked user we can use as lead."""
    r = requests.get(
        f"{BASE}/admin/users?limit=50",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    items = r.json().get("items") or []
    for u in items:
        if (
            not u.get("is_blocked")
            and not u.get("is_deleted")
            and not u.get("is_purged")
            and u.get("verified")
        ):
            return u
    for u in items:
        if not u.get("is_blocked") and not u.get("is_deleted"):
            return u
    raise RuntimeError("No usable user found in /admin/users")


def find_existing_group(token):
    """Find any open existing group to use for M2."""
    r = requests.get(
        f"{BASE}/admin/groups?status=open&limit=50",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    items = r.json().get("items") or []
    if items:
        return items[0]
    r = requests.get(
        f"{BASE}/admin/groups?limit=50",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    r.raise_for_status()
    items = r.json().get("items") or []
    return items[0] if items else None


# ─────────────────────────────────────────────────────────────────
# Mongo helpers (P2/P3/P4/P5)
# ─────────────────────────────────────────────────────────────────

async def mongo_seed_user(db, uid, name, phone, email, scheduled_dt, deleted_days_ago=31):
    now = datetime.now(timezone.utc)
    doc = {
        "id": uid,
        "is_deleted": True,
        "is_purged": False,
        "name": name,
        "phone": phone,
        "email": email,
        "verified": True,
        "deleted_at": (now - timedelta(days=deleted_days_ago)).isoformat(),
        "deletion_scheduled_at": scheduled_dt.isoformat() if scheduled_dt else None,
        "deletion_reason": "p1_purge_test",
        "last_session_id_before_delete": "sess_test_xyz",
        "current_session_id": "sess_test_xyz",
        "created_at": (now - timedelta(days=60)).isoformat(),
    }
    await db.users.replace_one({"id": uid}, doc, upsert=True)


async def mongo_read_user(db, uid):
    return await db.users.find_one({"id": uid}, {"_id": 0})


async def mongo_audit_for(db, uid):
    return await db.audit_logs.find_one(
        {"type": "account_purged_auto", "user_id": uid}, {"_id": 0}
    )


async def mongo_cleanup_user(db, uid):
    await db.users.delete_one({"id": uid})
    await db.audit_logs.delete_many({"user_id": uid, "type": "account_purged_auto"})


# ─────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────


def run_M1(token, base_cfg, lead_user):
    print("\n[M1] Maintenance Mode round trip")

    cfg = get_app_config(token)
    _check("GET /admin/app-config returns 200 + has ops", isinstance(cfg, dict) and "ops" in cfg)

    msg = "Down for testing"
    new_cfg = set_maintenance(token, cfg, on=True, msg=msg)
    _check("PUT /admin/app-config maintenance_mode=true → 200",
           new_cfg.get("ops", {}).get("maintenance_mode") is True,
           info=f"ops={new_cfg.get('ops')}")
    _check("Saved maintenance_message persisted",
           new_cfg.get("ops", {}).get("maintenance_message") == msg)

    body = {
        "lead_id": lead_user["id"],
        "title": "P1-Maint-Test-Bill",
        "total_amount": 12.50,
        "split_mode": "fast",
        "tax": 0.0,
        "tip": 0.0,
        "items": [],
    }
    r = requests.post(f"{BASE}/groups", json=body, timeout=30)
    _check("POST /api/groups during maintenance → 503",
           r.status_code == 503,
           info=f"status={r.status_code} body={r.text[:200]}")
    try:
        detail = r.json().get("detail")
    except Exception:
        detail = None
    _check("503 detail == 'Down for testing'",
           detail == msg,
           info=f"detail={detail!r}")

    new_cfg = set_maintenance(token, cfg, on=False)
    _check("PUT /admin/app-config maintenance_mode=false → 200",
           new_cfg.get("ops", {}).get("maintenance_mode") is False)

    r = requests.post(f"{BASE}/groups", json=body, timeout=30)
    _check("POST /api/groups after maintenance off → 200",
           r.status_code == 200,
           info=f"status={r.status_code} body={r.text[:300]}")

    created_gid = None
    if r.status_code == 200:
        try:
            created_gid = r.json().get("id")
        except Exception:
            pass
    return created_gid


def run_M2(token, base_cfg, existing_group):
    print("\n[M2] Maintenance affects ONLY POST /api/groups")

    cfg_before = get_app_config(token)
    set_maintenance(token, cfg_before, on=True, msg="M2 testing window")

    gid = existing_group["id"]

    r = requests.get(f"{BASE}/groups/{gid}", timeout=30)
    _check("GET /api/groups/{existing} during maintenance → 200",
           r.status_code == 200,
           info=f"status={r.status_code} body={r.text[:200]}")

    members = []
    if r.status_code == 200:
        try:
            members = r.json().get("members") or []
        except Exception:
            members = []
    user_id = (members[0]["user_id"] if members else existing_group.get("lead_id"))
    contrib_body = {
        "user_id": user_id,
        "amount": 0.01,
        "method": "credit_only",
    }
    r2 = requests.post(f"{BASE}/groups/{gid}/contribute", json=contrib_body, timeout=30)
    is_503_maint = False
    try:
        is_503_maint = (r2.status_code == 503 and r2.json().get("detail") == "M2 testing window")
    except Exception:
        is_503_maint = (r2.status_code == 503)
    _check("POST /groups/{existing}/contribute NOT blocked by maintenance",
           not is_503_maint,
           info=f"status={r2.status_code} body={r2.text[:300]}")

    set_maintenance(token, cfg_before, on=False)


def run_P1(token):
    print("\n[P1] Admin auth gating on POST /api/admin/users/run-purge-cron")

    r = requests.post(
        f"{BASE}/admin/users/run-purge-cron",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30,
    )
    _check("POST run-purge-cron with admin token → 200",
           r.status_code == 200,
           info=f"status={r.status_code} body={r.text[:300]}")
    if r.status_code == 200:
        body = r.json()
        for k in ("ok", "purged", "scanned", "skipped", "ran_at"):
            _check(f"  response has key '{k}'", k in body, info=f"body={body}")

    r = requests.post(f"{BASE}/admin/users/run-purge-cron", timeout=30)
    _check("POST run-purge-cron without auth → 401",
           r.status_code == 401,
           info=f"status={r.status_code} body={r.text[:200]}")


async def run_P2_P3_P4_P5(token):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    ts = int(time.time())
    u_p2 = "u_test_purge_p2"
    u_p3 = f"u_test_purge_p3_{ts}"
    u_p5 = f"u_test_purge_p5_{ts}"

    try:
        print("\n[P2] Past-grace user gets purged")
        await mongo_cleanup_user(db, u_p2)
        await mongo_seed_user(
            db, u_p2,
            name="Past Grace",
            phone="+15550009999",
            email="past_grace@test.com",
            scheduled_dt=datetime.now(timezone.utc) - timedelta(days=1),
            deleted_days_ago=31,
        )
        r = requests.post(
            f"{BASE}/admin/users/run-purge-cron",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        _check("P2 cron 200",
               r.status_code == 200,
               info=f"status={r.status_code} body={r.text[:200]}")
        purged = (r.json() or {}).get("purged", 0) if r.status_code == 200 else 0
        _check("P2 purged >= 1", purged >= 1, info=f"purged={purged}")

        u = await mongo_read_user(db, u_p2)
        _check("P2 user re-read present", u is not None)
        if u:
            _check("P2 is_purged=true", u.get("is_purged") is True, info=f"u={u}")
            _check("P2 name starts with 'Deleted User ('",
                   (u.get("name") or "").startswith("Deleted User ("),
                   info=f"name={u.get('name')!r}")
            _check("P2 phone is None", u.get("phone") is None, info=f"phone={u.get('phone')!r}")
            _check("P2 email is None", u.get("email") is None, info=f"email={u.get('email')!r}")
            _check("P2 current_session_id is None",
                   u.get("current_session_id") is None,
                   info=f"sess={u.get('current_session_id')!r}")
            _check("P2 purged_at is set", bool(u.get("purged_at")), info=f"purged_at={u.get('purged_at')!r}")

        audit = await mongo_audit_for(db, u_p2)
        _check("P2 audit_logs row exists with type=account_purged_auto", audit is not None,
               info=f"audit={audit}")
        if audit:
            _check("P2 audit.by_admin == 'system:purge-cron'",
                   audit.get("by_admin") == "system:purge-cron",
                   info=f"by_admin={audit.get('by_admin')!r}")
            _check("P2 audit.user_id matches",
                   audit.get("user_id") == u_p2)

        print("\n[P4] Idempotency — re-run does not double-purge")
        r2 = requests.post(
            f"{BASE}/admin/users/run-purge-cron",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        _check("P4 cron re-run 200", r2.status_code == 200,
               info=f"status={r2.status_code} body={r2.text[:200]}")
        if r2.status_code == 200:
            audit_count = await db.audit_logs.count_documents(
                {"type": "account_purged_auto", "user_id": u_p2}
            )
            _check("P4 P2 only has ONE audit row (no double-purge)",
                   audit_count == 1, info=f"audit_count={audit_count}")

        print("\n[P3] Within grace — user NOT purged")
        await mongo_cleanup_user(db, u_p3)
        await mongo_seed_user(
            db, u_p3,
            name="Within Grace",
            phone="+15550009111",
            email="within_grace@test.com",
            scheduled_dt=datetime.now(timezone.utc) + timedelta(days=5),
            deleted_days_ago=25,
        )
        r = requests.post(
            f"{BASE}/admin/users/run-purge-cron",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        _check("P3 cron 200", r.status_code == 200,
               info=f"status={r.status_code} body={r.text[:200]}")
        u = await mongo_read_user(db, u_p3)
        _check("P3 user re-read present", u is not None)
        if u:
            _check("P3 is_purged still false/missing",
                   not bool(u.get("is_purged")),
                   info=f"u.is_purged={u.get('is_purged')!r}")
            _check("P3 name unchanged ('Within Grace')",
                   u.get("name") == "Within Grace",
                   info=f"name={u.get('name')!r}")
            _check("P3 phone unchanged", u.get("phone") == "+15550009111",
                   info=f"phone={u.get('phone')!r}")
            _check("P3 email unchanged", u.get("email") == "within_grace@test.com",
                   info=f"email={u.get('email')!r}")

        print("\n[P5] Edge case — missing deletion_scheduled_at")
        await mongo_cleanup_user(db, u_p5)
        await mongo_seed_user(
            db, u_p5,
            name="No Schedule",
            phone="+15550008888",
            email="noschedule@test.com",
            scheduled_dt=None,
            deleted_days_ago=40,
        )
        r = requests.post(
            f"{BASE}/admin/users/run-purge-cron",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        _check("P5 cron 200 (no crash)", r.status_code == 200,
               info=f"status={r.status_code} body={r.text[:200]}")
        u = await mongo_read_user(db, u_p5)
        _check("P5 user re-read present", u is not None)
        if u:
            _check("P5 is_purged still false/missing",
                   not bool(u.get("is_purged")),
                   info=f"u.is_purged={u.get('is_purged')!r}")
            _check("P5 name unchanged", u.get("name") == "No Schedule",
                   info=f"name={u.get('name')!r}")
            _check("P5 phone unchanged", u.get("phone") == "+15550008888",
                   info=f"phone={u.get('phone')!r}")

    finally:
        for uid in (u_p2, u_p3, u_p5):
            try:
                await mongo_cleanup_user(db, uid)
            except Exception as e:
                print(f"  ⚠ cleanup {uid} failed: {e}")
        client.close()


def cleanup_created_group(gid):
    if not gid:
        return
    try:
        import pymongo
        client = pymongo.MongoClient(MONGO_URL)
        client[DB_NAME].groups.delete_one({"id": gid})
        client.close()
        print(f"  🧹 cleaned up group {gid}")
    except Exception as e:
        print(f"  ⚠ cleanup group {gid} failed: {e}")


def main():
    print("=" * 60)
    print("P1 Follow-ups Backend Tests")
    print("=" * 60)

    token = admin_login()
    print(f"✅ admin login OK (token len={len(token)})")
    base_cfg = get_app_config(token)
    print(f"✅ initial app-config fetched, ops.maintenance_mode={base_cfg.get('ops', {}).get('maintenance_mode')}")

    if base_cfg.get("ops", {}).get("maintenance_mode"):
        set_maintenance(token, base_cfg, on=False)
        base_cfg = get_app_config(token)

    lead_user = find_active_user(token)
    print(f"✅ lead user: id={lead_user['id']} name={lead_user.get('name')!r}")

    existing_group = find_existing_group(token)
    print(f"✅ existing group: id={existing_group['id'] if existing_group else None}")

    created_gid = None
    try:
        created_gid = run_M1(token, base_cfg, lead_user)
        if existing_group:
            run_M2(token, base_cfg, existing_group)
        else:
            print("[M2] SKIPPED — no existing group available")
        run_P1(token)
        asyncio.run(run_P2_P3_P4_P5(token))
    finally:
        try:
            cfg_now = get_app_config(token)
            if cfg_now.get("ops", {}).get("maintenance_mode"):
                set_maintenance(token, cfg_now, on=False)
                print("🧹 restored maintenance_mode=false")
        except Exception as e:
            print(f"  ⚠ final maintenance restore failed: {e}")

        cleanup_created_group(created_gid)

    print("\n" + "=" * 60)
    print(f"RESULTS  PASS={PASS}  FAIL={FAIL}")
    if FAILS:
        print("\nFAILURES:")
        for label, info in FAILS:
            print(f"  - {label}\n     {info}")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
