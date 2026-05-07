"""Auth + user fetch routes (extracted from server.py — Batch B)."""
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from core import (
    RegisterIn, UserOut, SendOtpIn, VerifyOtpIn,
    new_id, now_iso, generate_unique_referral_code, _maybe_grant_referral_rewards,
)

logger = logging.getLogger(__name__)


async def _migrate_placeholder_into_existing(db, placeholder_id: str, existing_id: str) -> dict:
    """Transfer all of placeholder's group memberships, leadership, assignments,
    contributions, repayments, and credits to the existing verified account.

    Used when verify-otp finds that the placeholder's phone is already linked to
    a different verified user. The placeholder is then safely deleted.

    Idempotent: if no docs match, it's a no-op.
    """
    if placeholder_id == existing_id:
        return {"groups_touched": 0, "leadership_transferred": 0, "credits_moved": 0}

    groups_touched = 0
    leadership_transferred = 0

    # Pull every group the placeholder participates in (as member, lead, contributor, etc.)
    cursor = db.groups.find(
        {
            "$or": [
                {"lead_id": placeholder_id},
                {"members.user_id": placeholder_id},
                {"contributions.user_id": placeholder_id},
                {"repayments.user_id": placeholder_id},
                {"assignments.user_id": placeholder_id},
                {"shortfall_obligations.user_id": placeholder_id},
                {"notifications.user_id": placeholder_id},
            ]
        },
        {"_id": 0},
    )
    groups = await cursor.to_list(length=None)

    for g in groups:
        gid = g["id"]
        changed = False

        # ---- 1. Transfer leadership
        if g.get("lead_id") == placeholder_id:
            g["lead_id"] = existing_id
            leadership_transferred += 1
            changed = True

        # ---- 2. Members: replace placeholder, dedupe with existing if already present
        new_members = []
        existing_seen = False
        placeholder_role = None
        for m in g.get("members", []):
            if m.get("user_id") == placeholder_id:
                placeholder_role = m.get("role")
                continue   # drop, will re-add below
            if m.get("user_id") == existing_id:
                existing_seen = True
            new_members.append(m)
        if placeholder_role is not None:
            if not existing_seen:
                new_members.append({
                    "user_id": existing_id,
                    "role": placeholder_role,
                    "joined_at": now_iso(),
                })
            else:
                # If existing was already a member but placeholder was the lead,
                # promote existing to lead role.
                if placeholder_role == "lead":
                    for nm in new_members:
                        if nm.get("user_id") == existing_id:
                            nm["role"] = "lead"
                            break
            g["members"] = new_members
            changed = True

        # ---- 3. Replace user_id in nested arrays (idempotent)
        for arr_key in ("contributions", "repayments", "assignments",
                        "shortfall_obligations", "notifications"):
            arr = g.get(arr_key) or []
            touched = False
            for item in arr:
                if item.get("user_id") == placeholder_id:
                    item["user_id"] = existing_id
                    touched = True
            if touched:
                g[arr_key] = arr
                changed = True

        # ---- 4. shortfall_settlement.beneficiaries / funder_id
        ss = g.get("shortfall_settlement")
        if ss:
            if ss.get("funder_id") == placeholder_id:
                ss["funder_id"] = existing_id
                changed = True
            ben = ss.get("beneficiaries") or []
            if placeholder_id in ben:
                ben = [existing_id if b == placeholder_id else b for b in ben]
                # Dedupe in case existing was already a beneficiary
                seen = set()
                ben = [b for b in ben if not (b in seen or seen.add(b))]
                ss["beneficiaries"] = ben
                changed = True

        if changed:
            groups_touched += 1
            await db.groups.update_one({"id": gid}, {"$set": g})

    # ---- 5. Move credits ledger rows
    credit_res = await db.credits.update_many(
        {"user_id": placeholder_id}, {"$set": {"user_id": existing_id}}
    )

    # ---- 6. Reassign referrals where this placeholder is a referrer
    ref_res = await db.users.update_many(
        {"referred_by_user_id": placeholder_id}, {"$set": {"referred_by_user_id": existing_id}}
    )

    return {
        "groups_touched": groups_touched,
        "leadership_transferred": leadership_transferred,
        "credits_moved": credit_res.modified_count,
        "referrals_moved": ref_res.modified_count,
    }


def attach_auth_routes(router: APIRouter, db):

    @router.post("/auth/register", response_model=UserOut)
    async def register(body: RegisterIn):
        if not body.name or not body.name.strip():
            raise HTTPException(400, "Name is required")

        # C1: validate optional referral code
        referred_by_user_id = None
        if body.referral_code:
            rc = body.referral_code.strip().upper()
            if rc:
                referrer = await db.users.find_one(
                    {"referral_code": rc, "is_blocked": {"$ne": True}}, {"_id": 0}
                )
                if not referrer:
                    raise HTTPException(400, "Invalid referral code")
                referred_by_user_id = referrer["id"]

        referral_code = await generate_unique_referral_code(db)
        user = {
            "id": new_id("u_"),
            "name": body.name.strip(),
            "phone": None,
            "verified": False,
            "created_at": now_iso(),
            "referral_code": referral_code,
            "referred_by_user_id": referred_by_user_id,
            "referral_reward_granted": False,
        }
        await db.users.insert_one(user.copy())
        return UserOut(**user)

    @router.post("/auth/send-otp")
    async def send_otp(body: SendOtpIn):
        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        # Phase H6.2 — mode-aware OTP. In LIVE mode the code is cryptographically
        # random and never returned in the response. In MOCK mode the code is
        # "123456" and surfaced in `message` so demo/dev can sign in without SMS.
        from otp_helpers import generate_and_send_otp, build_otp_response
        code, sent_real, info, mode = await generate_and_send_otp(
            db=db,
            phone=body.phone,
            body_template="Your KWIKPAY verification code is {code}. Valid for 5 minutes.",
            purpose_label="send-otp",
        )
        await db.otp_codes.update_one(
            {"user_id": body.user_id},
            {"$set": {"phone": body.phone, "code": code, "created_at": now_iso(), "mode": mode}},
            upsert=True,
        )
        if mode == "live" and not sent_real:
            # Code was generated but the SMS provider failed. Don't expose code.
            raise HTTPException(
                502,
                detail=f"Could not send verification SMS. {info}",
            )
        return build_otp_response(
            code, sent_real, info, mode,
            label_for_user="OTP",
            success_msg_live="OTP sent via SMS. Check your phone.",
        )

    # Phase H2 — phone-lookup endpoint. Used by the auth flow BEFORE verify-otp
    # to detect the "phone already registered to another account" case so the
    # client can show a confirmation dialog.
    @router.get("/auth/lookup-phone")
    async def lookup_phone(phone: str, exclude_user_id: str = ""):
        if not phone or not phone.strip():
            return {"exists": False}
        existing = await db.users.find_one(
            {
                "phone": phone.strip(),
                "verified": True,
                "id": {"$ne": exclude_user_id} if exclude_user_id else {"$exists": True},
            },
            {"_id": 0, "id": 1, "name": 1, "is_blocked": 1},
        )
        if not existing:
            return {"exists": False}
        return {
            "exists": True,
            "name": existing.get("name"),
            "blocked": bool(existing.get("is_blocked")),
        }

    @router.post("/auth/verify-otp")
    async def verify_otp(body: VerifyOtpIn):
        record = await db.otp_codes.find_one({"user_id": body.user_id}, {"_id": 0})
        if not record or record.get("code") != body.code or record.get("phone") != body.phone:
            raise HTTPException(400, "Invalid OTP code")

        existing = await db.users.find_one(
            {"phone": body.phone, "verified": True, "id": {"$ne": body.user_id}},
            {"_id": 0},
        )

        # ── Path A: Phone already linked to another verified account ──
        if existing:
            if existing.get("is_blocked"):
                # Don't delete the placeholder yet — let the user contact support.
                raise HTTPException(403, "This account has been blocked. Please contact support.")

            # Phase H2 — REQUIRE explicit confirmation before merging.
            # Otherwise return 409 with the existing name so the client can show
            # "An account with this number is already registered as <name>. Use it?"
            if not body.confirm_existing:
                return JSONResponse(
                    status_code=409,
                    content={
                        "code": "phone_already_registered",
                        "existing_name": existing.get("name"),
                        "message": (
                            f"An account with this number is already registered as "
                            f"\"{existing.get('name')}\". Do you want to sign in to that account?"
                        ),
                    },
                )

            # User confirmed. Migrate the placeholder's groups/credits/referrals
            # over to the existing account. CRITICAL: we DO NOT rename the existing
            # account — its original name is preserved.
            try:
                summary = await _migrate_placeholder_into_existing(
                    db, placeholder_id=body.user_id, existing_id=existing["id"]
                )
                logger.info(f"[verify-otp] merge {body.user_id}->{existing['id']}: {summary}")
            except Exception as e:
                logger.exception(f"[verify-otp] migration failed: {e}")
                raise HTTPException(500, "Failed to merge accounts. Please contact support.")

            # If the existing account never had a referral code, give it one.
            if not existing.get("referral_code"):
                code = await generate_unique_referral_code(db)
                await db.users.update_one({"id": existing["id"]}, {"$set": {"referral_code": code}})
                existing["referral_code"] = code

            # Delete the placeholder (its data has already been migrated).
            await db.users.delete_one({"id": body.user_id})
            await db.otp_codes.delete_one({"user_id": body.user_id})

            existing["verified"] = True
            existing["phone"] = body.phone
            await _maybe_grant_referral_rewards(db, existing)
            return UserOut(**existing).model_dump()

        # ── Path B: Brand-new phone for the placeholder — just verify it ──
        await db.users.update_one(
            {"id": body.user_id}, {"$set": {"phone": body.phone, "verified": True}}
        )
        user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
        if user and not user.get("referral_code"):
            code = await generate_unique_referral_code(db)
            await db.users.update_one({"id": user["id"]}, {"$set": {"referral_code": code}})
            user["referral_code"] = code
        if user:
            await _maybe_grant_referral_rewards(db, user)
        return UserOut(**user).model_dump()

    @router.get("/users/{user_id}", response_model=UserOut)
    async def get_user(user_id: str):
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        return UserOut(**user)
