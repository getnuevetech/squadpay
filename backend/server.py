from fastapi import FastAPI, APIRouter, HTTPException, Request
from dotenv import load_dotenv
from starlette.middleware.cors import CORSMiddleware
from motor.motor_asyncio import AsyncIOMotorClient
import os
import logging
import json
import re
import secrets
import string
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import uuid
from datetime import datetime, timezone


ROOT_DIR = Path(__file__).parent
load_dotenv(ROOT_DIR / ".env")

# MongoDB connection
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]

app = FastAPI()
api_router = APIRouter(prefix="/api")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")


# ------------- Helpers -------------

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:10]}"


def new_short_code(length: int = 8) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


# C1: referral code helpers — 6-char uppercase, drop confusing chars (0/O/1/I)
_REFERRAL_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _gen_referral_code(length: int = 6) -> str:
    return "".join(secrets.choice(_REFERRAL_ALPHABET) for _ in range(length))


async def generate_unique_referral_code(db_) -> str:
    for _ in range(20):
        code = _gen_referral_code()
        exists = await db_.users.find_one({"referral_code": code}, {"_id": 0, "id": 1})
        if not exists:
            return code
    # Vanishingly unlikely fallback
    return _gen_referral_code(8)


async def _get_referral_settings() -> dict:
    """Read referral system settings (created lazily with safe defaults)."""
    rec = await db.app_settings.find_one({"key": "referrals"}, {"_id": 0})
    if not rec:
        rec = {
            "key": "referrals",
            "enabled": False,
            "referrer_credit": 0.0,
            "referee_credit": 0.0,
            "updated_at": now_iso(),
        }
        await db.app_settings.insert_one(rec.copy())
    return rec


async def _maybe_grant_referral_rewards(user: dict):
    """Grant pending credits to referrer + referee on FIRST verify, idempotent.

    Stores credit ledger rows in `db.credits`. Activation/consumption is handled
    by Phase C2 (credits/discounts). For now we record `pending` rows that the
    admin can see and Phase C2 will turn into spendable credits.
    """
    if not user or not user.get("referred_by_user_id"):
        return
    if user.get("referral_reward_granted"):
        return
    settings = await _get_referral_settings()
    if not settings.get("enabled"):
        # Mark as granted=True so we don't keep checking; rewards are 0 anyway.
        await db.users.update_one({"id": user["id"]}, {"$set": {"referral_reward_granted": True}})
        return

    referrer_amt = float(settings.get("referrer_credit") or 0)
    referee_amt = float(settings.get("referee_credit") or 0)
    referrer_id = user["referred_by_user_id"]

    rows = []
    if referrer_amt > 0:
        rows.append({
            "id": new_id("cr_"),
            "user_id": referrer_id,
            "amount": round(referrer_amt, 2),
            "kind": "referral_referrer",
            "source_user_id": user["id"],
            "status": "active",  # C2: spendable immediately
            "note": f"Referral reward: {user.get('name')} signed up with your code.",
            "created_at": now_iso(),
        })
    if referee_amt > 0:
        rows.append({
            "id": new_id("cr_"),
            "user_id": user["id"],
            "amount": round(referee_amt, 2),
            "kind": "referral_referee",
            "source_user_id": referrer_id,
            "status": "active",
            "note": "Welcome bonus for using a referral code.",
            "created_at": now_iso(),
        })
    if rows:
        await db.credits.insert_many([r.copy() for r in rows])
    await db.users.update_one(
        {"id": user["id"]}, {"$set": {"referral_reward_granted": True}}
    )


# ---------------- Phase C2: credits + discounts helpers ----------------

async def _activate_pending_credits():
    """One-shot migration: flip any leftover 'pending' credits to 'active'.

    Pre-C2 referral rewards were stored as pending. C2 makes them spendable.
    Idempotent — safe to call on every startup. Sets consumed_amount=0 if missing.
    """
    try:
        # backfill consumed_amount on any old rows
        await db.credits.update_many(
            {"consumed_amount": {"$exists": False}},
            {"$set": {"consumed_amount": 0}},
        )
        res = await db.credits.update_many(
            {"status": "pending"}, {"$set": {"status": "active"}}
        )
        if res.modified_count:
            logger.info(f"[c2] activated {res.modified_count} pending credits")
    except Exception as e:
        logger.warning(f"[c2] pending->active migration failed: {e}")


async def _user_credit_balance(user_id: str) -> float:
    """Sum of (amount - consumed_amount) across active credits for a user."""
    rows = await db.credits.find(
        {"user_id": user_id, "status": "active"},
        {"_id": 0, "amount": 1, "consumed_amount": 1},
    ).to_list(length=None)
    bal = 0.0
    for r in rows:
        bal += float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0)
    return round(max(0.0, bal), 2)


async def _consume_user_credits(user_id: str, amount: float, group_id: str, contribution_id: str) -> tuple[float, list]:
    """Consume up to `amount` from user's active credits, FIFO by created_at.

    Returns (actually_consumed, list_of_consumption_records).
    Each consumption record: {credit_id, amount, group_id, contribution_id, at}.
    """
    if amount <= 0:
        return 0.0, []
    rows = await db.credits.find(
        {"user_id": user_id, "status": "active"}, {"_id": 0}
    ).sort("created_at", 1).to_list(length=None)
    remaining = round(float(amount), 2)
    consumed_total = 0.0
    consumption_log: list = []
    for r in rows:
        if remaining <= 0:
            break
        avail = round(float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0), 2)
        if avail <= 0:
            continue
        take = min(avail, remaining)
        new_consumed = round(float(r.get("consumed_amount") or 0) + take, 2)
        new_status = "consumed" if new_consumed + 0.001 >= float(r["amount"]) else "active"
        await db.credits.update_one(
            {"id": r["id"]},
            {"$set": {
                "consumed_amount": new_consumed,
                "status": new_status,
                "last_consumed_at": now_iso(),
            },
             "$push": {
                "consumption_events": {
                    "amount": round(take, 2),
                    "group_id": group_id,
                    "contribution_id": contribution_id,
                    "at": now_iso(),
                }
            }},
        )
        consumption_log.append({
            "credit_id": r["id"],
            "amount": round(take, 2),
            "group_id": group_id,
            "contribution_id": contribution_id,
            "at": now_iso(),
        })
        remaining = round(remaining - take, 2)
        consumed_total = round(consumed_total + take, 2)
    return consumed_total, consumption_log


def _apply_group_discount(subtotal_with_tax_tip: float, discount: dict | None) -> tuple[float, float]:
    """Return (final_total, discount_amount). discount = {type: 'flat'|'percent', value: number}.

    'flat' = flat $ off, capped at subtotal. 'percent' = percentage off (0–100).
    """
    if not discount:
        return round(subtotal_with_tax_tip, 2), 0.0
    dtype = discount.get("type")
    val = float(discount.get("value") or 0)
    if val <= 0:
        return round(subtotal_with_tax_tip, 2), 0.0
    if dtype == "percent":
        amount = round(subtotal_with_tax_tip * min(val, 100) / 100.0, 2)
    else:
        amount = min(round(val, 2), round(subtotal_with_tax_tip, 2))
    final = max(0.0, round(subtotal_with_tax_tip - amount, 2))
    return final, round(amount, 2)



def clean_mongo(doc: dict) -> dict:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


# ------------- Models -------------

class RegisterIn(BaseModel):
    name: str
    referral_code: Optional[str] = None  # C1: optional invite code from another user


class UserOut(BaseModel):
    id: str
    name: str
    phone: Optional[str] = None
    verified: bool = False
    created_at: str
    referral_code: Optional[str] = None  # C1
    referred_by_user_id: Optional[str] = None  # C1


class SendOtpIn(BaseModel):
    user_id: str
    phone: str


class VerifyOtpIn(BaseModel):
    user_id: str
    phone: str
    code: str


class ItemIn(BaseModel):
    name: str
    price: float
    quantity: int = 1


class CreateGroupIn(BaseModel):
    lead_id: str
    title: str
    total_amount: float
    split_mode: str = "itemized"  # fast | smart | itemized
    tax: float = 0.0
    tip: float = 0.0
    items: List[ItemIn] = []


class JoinGroupIn(BaseModel):
    user_id: str


class UpdateItemsIn(BaseModel):
    items: List[ItemIn]


class AssignIn(BaseModel):
    user_id: str
    item_id: str
    quantity: int  # 0 means clear


class PayIn(BaseModel):
    user_id: str  # lead user id
    shortfall_mode: Optional[str] = None  # 'lead' | 'member' | 'split_equal'
    is_loan: Optional[bool] = True
    funder_member_id: Optional[str] = None  # required when shortfall_mode == 'member'


class UpdateGroupMetaIn(BaseModel):
    user_id: str  # must be the lead
    title: Optional[str] = None
    tax: Optional[float] = None
    tip: Optional[float] = None



class RepayIn(BaseModel):
    user_id: str
    amount: float


class ContributeIn(BaseModel):
    user_id: str
    amount: Optional[float] = None  # If None, contributes user's full share
    notify_on_settled: bool = False
    notify_on_settled: Optional[bool] = False
    origin_url: Optional[str] = None  # Required when cash payment is needed (Phase F1 — Stripe Checkout)


class AppendItemsIn(BaseModel):
    user_id: str
    items: List[ItemIn]


class ItemPatchIn(BaseModel):
    user_id: str
    quantity_delta: int


# ------------- Pricing constants -------------
TRANSACTION_FEE_RATE = 0.03  # 3% per-member surcharge
PLATFORM_FEE = 0.03  # 3 cents flat per member


def gen_virtual_card() -> Optional[dict]:
    """DEPRECATED: Mock virtual card generator removed in Phase F1.

    Real virtual cards are now issued via Stripe Issuing when a group is fully funded.
    See /app/backend/issuing.py :: issue_group_card(). This stub returns None so
    nothing is mocked at group-creation time.
    """
    return None


class ScanReceiptIn(BaseModel):
    image_base64: str


# ------------- Auth -------------

@api_router.post("/auth/register", response_model=UserOut)
async def register(body: RegisterIn):
    if not body.name or not body.name.strip():
        raise HTTPException(400, "Name is required")

    # C1: validate optional referral code
    referred_by_user_id: Optional[str] = None
    if body.referral_code:
        rc = body.referral_code.strip().upper()
        if rc:
            referrer = await db.users.find_one(
                {"referral_code": rc, "is_blocked": {"$ne": True}}, {"_id": 0}
            )
            if not referrer:
                raise HTTPException(400, "Invalid referral code")
            referred_by_user_id = referrer["id"]

    # C1: every user gets a unique referral code at signup
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


@api_router.post("/auth/send-otp")
async def send_otp(body: SendOtpIn):
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    # Mock OTP code is always 123456 (so testing/CI continues to work).
    # If Twilio is enabled & configured, also send a real SMS notification with the code.
    code = "123456"
    await db.otp_codes.update_one(
        {"user_id": body.user_id},
        {"$set": {"phone": body.phone, "code": code, "created_at": now_iso()}},
        upsert=True,
    )
    sent_real = False
    info = "Twilio disabled — mock OTP"
    try:
        from integrations import send_sms_via_twilio
        sent_real, info = await send_sms_via_twilio(
            db, body.phone, f"Your GroupPay verification code is {code}. Valid for 5 minutes."
        )
    except Exception as e:
        logger.warning(f"[send-otp] twilio attempt failed: {e}")
    return {
        "ok": True,
        "message": f"OTP sent. Use {code}" if not sent_real else "OTP SMS sent",
        "mocked": not sent_real,
        "twilio_info": info,
    }


@api_router.post("/auth/verify-otp", response_model=UserOut)
async def verify_otp(body: VerifyOtpIn):
    record = await db.otp_codes.find_one({"user_id": body.user_id}, {"_id": 0})
    if not record or record.get("code") != body.code or record.get("phone") != body.phone:
        raise HTTPException(400, "Invalid OTP code")
    # PERSISTENT USERS: if a verified user already exists with this phone,
    # collapse to that user (do not create a duplicate). The throwaway
    # placeholder created by /auth/register is removed and the existing
    # user_id is returned. The session client will switch to it.
    existing = await db.users.find_one(
        {"phone": body.phone, "verified": True, "id": {"$ne": body.user_id}}, {"_id": 0}
    )
    if existing:
        if existing.get("is_blocked"):
            # Drop placeholder so we don't leak orphan rows
            await db.users.delete_one({"id": body.user_id})
            raise HTTPException(403, "This account has been blocked. Please contact support.")
        # If client supplied a different name, refresh the existing user's name.
        try:
            placeholder = await db.users.find_one({"id": body.user_id}, {"_id": 0})
            patch: dict = {}
            if placeholder and placeholder.get("name") and placeholder["name"] != existing["name"]:
                patch["name"] = placeholder["name"]
                existing["name"] = placeholder["name"]
            # C1: transfer referral linkage from placeholder if existing has none yet
            if placeholder and placeholder.get("referred_by_user_id") and not existing.get("referred_by_user_id"):
                # Avoid self-referral loop
                if placeholder["referred_by_user_id"] != existing["id"]:
                    patch["referred_by_user_id"] = placeholder["referred_by_user_id"]
                    existing["referred_by_user_id"] = placeholder["referred_by_user_id"]
            # C1: backfill referral_code on legacy users
            if not existing.get("referral_code"):
                code = await generate_unique_referral_code(db)
                patch["referral_code"] = code
                existing["referral_code"] = code
            if patch:
                await db.users.update_one({"id": existing["id"]}, {"$set": patch})
        except Exception:
            pass
        # Drop the throwaway placeholder
        await db.users.delete_one({"id": body.user_id})
        existing["verified"] = True
        existing["phone"] = body.phone
        # C1: grant referral rewards on first verify (idempotent)
        await _maybe_grant_referral_rewards(existing)
        return UserOut(**existing)

    await db.users.update_one(
        {"id": body.user_id}, {"$set": {"phone": body.phone, "verified": True}}
    )
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    # C1: backfill referral_code if missing (legacy users)
    if user and not user.get("referral_code"):
        code = await generate_unique_referral_code(db)
        await db.users.update_one({"id": user["id"]}, {"$set": {"referral_code": code}})
        user["referral_code"] = code
    # C1: grant referral rewards on first verify
    if user:
        await _maybe_grant_referral_rewards(user)
    return UserOut(**user)


@api_router.get("/users/{user_id}", response_model=UserOut)
async def get_user(user_id: str):
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    return UserOut(**user)


# ------------- Groups -------------

async def _recompute_group(group: dict) -> dict:
    """Compute per-user breakdown and totals. Mutates nothing in DB; returns enriched dict."""
    items = group.get("items", [])
    assignments = group.get("assignments", [])  # list of {user_id,item_id,quantity}
    members = group.get("members", [])
    split_mode = group.get("split_mode", "itemized")
    subtotal = sum(i["price"] * i["quantity"] for i in items)
    tax = group.get("tax", 0.0)
    tip = group.get("tip", 0.0)
    total = group.get("total_amount") or (subtotal + tax + tip)

    per_user_food: Dict[str, float] = {m["user_id"]: 0.0 for m in members}
    unclaimed_items: List[Dict[str, Any]] = []

    if split_mode == "fast":
        # Equal split among members
        if members:
            equal = total / len(members)
            per_user = [
                {"user_id": m["user_id"], "food": round(equal, 2), "tax_tip": 0.0, "total": round(equal, 2)}
                for m in members
            ]
        else:
            per_user = []
    else:
        # Itemized / smart: food via assignments, tax+tip split proportionally
        for item in items:
            item_id = item["id"]
            claimed_qty = sum(a["quantity"] for a in assignments if a["item_id"] == item_id)
            remaining = item["quantity"] - claimed_qty
            if remaining > 0:
                unclaimed_items.append({"item_id": item_id, "name": item["name"], "remaining": remaining, "price": item["price"]})
            for a in assignments:
                if a["item_id"] == item_id and a["user_id"] in per_user_food:
                    per_user_food[a["user_id"]] += a["quantity"] * item["price"]
        # Proportional tax+tip allocation
        extras = tax + tip
        per_user = []
        for m in members:
            food = per_user_food.get(m["user_id"], 0.0)
            share = (food / subtotal) if subtotal > 0 else 0.0
            extra = round(share * extras, 2)
            per_user.append({
                "user_id": m["user_id"],
                "food": round(food, 2),
                "tax_tip": extra,
                "total": round(food + extra, 2),
            })

    fully_claimed = (split_mode == "fast") or (len(unclaimed_items) == 0 and subtotal > 0)

    # Apply per-user platform + transaction fees (itemized, immutable)
    for p in per_user:
        merchant_share = round(p["total"], 2)
        p["merchant_share"] = merchant_share
        p["transaction_fee"] = round(merchant_share * TRANSACTION_FEE_RATE, 2)
        p["platform_fee"] = round(PLATFORM_FEE, 2)
        p["total"] = round(merchant_share + p["transaction_fee"] + p["platform_fee"], 2)

    # Funding overlay: contributions, repayments, outstanding per user
    contributions = group.get("contributions", [])
    repayments = group.get("repayments", [])
    contrib_by_user: Dict[str, float] = {}
    for c in contributions:
        contrib_by_user[c["user_id"]] = contrib_by_user.get(c["user_id"], 0.0) + float(c["amount"])
    repaid_by_user: Dict[str, float] = {}
    for r in repayments:
        repaid_by_user[r["user_id"]] = repaid_by_user.get(r["user_id"], 0.0) + float(r["amount"])

    lead_id = group.get("lead_id")
    settlement = group.get("shortfall_settlement") or {}
    gift_active = bool(settlement) and not settlement.get("is_loan", True)
    beneficiaries = set(settlement.get("beneficiaries") or [])

    # Shortfall obligations: extra amounts a user owes BEFORE the merchant is paid.
    # Created when lead picks 'member' or 'split_equal' settlement.
    obligations = group.get("shortfall_obligations", []) or []
    obligation_by_user: Dict[str, float] = {}
    for o in obligations:
        obligation_by_user[o["user_id"]] = obligation_by_user.get(o["user_id"], 0.0) + float(o.get("amount", 0))

    for p in per_user:
        uid = p["user_id"]
        p["contributed"] = round(contrib_by_user.get(uid, 0.0), 2)
        p["repaid"] = round(repaid_by_user.get(uid, 0.0), 2)
        p["shortfall_owed"] = round(obligation_by_user.get(uid, 0.0), 2)
        if uid == lead_id:
            # Lead's own share is implicitly covered when they pay the bill (or when fully group-funded).
            # Lead can still owe a shortfall obligation (rare, only if assigned to themselves).
            p["outstanding"] = round(max(0.0, p["shortfall_owed"] - p["repaid"]), 2)
        elif gift_active and uid in beneficiaries:
            # Shortfall covered as a gift — beneficiary owes nothing.
            p["outstanding"] = 0.0
        else:
            # Total amount this user is on the hook for = their normal share + any shortfall obligation
            total_owed = p["total"] + p["shortfall_owed"]
            p["outstanding"] = round(max(0.0, total_owed - p["contributed"] - p["repaid"]), 2)

    total_contributed = round(sum(contrib_by_user.values()), 2)
    total_repaid = round(sum(repaid_by_user.values()), 2)
    total_amount = group.get("total_amount") or round(total, 2)
    lead_shortfall = group.get("lead_shortfall")
    if lead_shortfall is None:
        lead_shortfall = round(max(0.0, total_amount - total_contributed), 2)

    # Refresh virtual card balance from contributions (mocked)
    virtual_card = group.get("virtual_card")
    if virtual_card:
        virtual_card = {**virtual_card, "balance": total_contributed}

    # Derived 4-state machine: contributing | contributed | repaying | settled
    raw_status = group.get("status", "open")
    settlement = group.get("shortfall_settlement") or {}
    has_outstanding = any(p["outstanding"] > 0.01 for p in per_user)
    # "repaying" is specifically about the LEAD being repaid for fronting cash.
    lead_loaned = (
        settlement.get("mode") == "lead"
        and settlement.get("is_loan", False)
        and any(
            p["outstanding"] > 0.01
            for p in per_user
            if p["user_id"] in (settlement.get("beneficiaries") or [])
        )
    )
    if raw_status == "open":
        if total_contributed + 0.01 >= total_amount and not has_outstanding:
            derived_status = "contributed"
        else:
            derived_status = "contributing"
    elif raw_status == "paid":
        derived_status = "repaying" if lead_loaned else "settled"
    else:  # closed
        derived_status = "settled"

    return {
        **group,
        "virtual_card": virtual_card,
        "subtotal": round(subtotal, 2),
        "total": round(total, 2),
        "per_user": per_user,
        "unclaimed": unclaimed_items,
        "fully_claimed": fully_claimed,
        "derived_status": derived_status,
        "funding": {
            "total_contributed": total_contributed,
            "total_repaid": total_repaid,
            "lead_shortfall": round(lead_shortfall, 2),
            "remaining_to_collect": round(max(0.0, total_amount - total_contributed), 2),
            "fees_total": round(sum(p["transaction_fee"] + p["platform_fee"] for p in per_user), 2),
        },
    }


async def _load_group_enriched(group_id: str) -> dict:
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    # Attach member names
    user_ids = [m["user_id"] for m in group.get("members", [])]
    users = await db.users.find({"id": {"$in": user_ids}}, {"_id": 0}).to_list(1000)
    user_map = {u["id"]: u for u in users}
    for m in group.get("members", []):
        u = user_map.get(m["user_id"], {})
        m["name"] = u.get("name", "Unknown")
        m["phone"] = u.get("phone")
        m["verified"] = u.get("verified", False)
    enriched = await _recompute_group(group)
    return enriched


@api_router.post("/groups")
async def create_group(body: CreateGroupIn):
    user = await db.users.find_one({"id": body.lead_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "Lead user not found")
    if user.get("is_blocked"):
        raise HTTPException(403, "Your account has been blocked. Please contact support.")
    gid = new_id("g_")
    code = new_short_code(8)
    items = []
    for it in body.items:
        items.append({"id": new_id("it_"), "name": it.name, "price": it.price, "quantity": it.quantity})
    # Phase C2: apply lead's auto-discount (if any) to this group at creation
    discount_doc = None
    discount_applied = 0.0
    final_total = float(body.total_amount or 0)
    auto = user.get("lead_auto_discount") or None
    if auto and auto.get("value", 0) > 0:
        final_total, discount_applied = _apply_group_discount(float(body.total_amount or 0), auto)
        if discount_applied > 0:
            discount_doc = {
                "type": auto.get("type", "flat"),
                "value": float(auto.get("value") or 0),
                "amount": discount_applied,
                "note": auto.get("note") or "Lead auto-discount",
                "source": "lead_auto",
                "applied_at": now_iso(),
                "applied_by": "system",
            }
    group = {
        "id": gid,
        "code": code,
        "lead_id": body.lead_id,
        "title": body.title or "Group Bill",
        "total_amount": round(final_total, 2),
        "original_total_amount": float(body.total_amount or 0),
        "tax": body.tax,
        "tip": body.tip,
        "split_mode": body.split_mode,
        "status": "open",  # open | paid | closed
        "funding_mode": None,  # group | lead | shortfall
        "virtual_card": None,  # Phase F1: Real Stripe Issuing card is created on full funding
        "items": items,
        "assignments": [],
        "members": [{"user_id": body.lead_id, "role": "lead", "joined_at": now_iso()}],
        "contributions": [],  # {user_id, amount, cash_paid, credit_applied, ...}
        "repayments": [],  # {user_id, amount, at}
        "lead_paid_at": None,
        "discount": discount_doc,  # {type, value, amount, note, source, applied_at, applied_by}
        "created_at": now_iso(),
    }
    await db.groups.insert_one(group.copy())
    return await _load_group_enriched(gid)


@api_router.get("/groups/{group_id}")
async def get_group(group_id: str):
    return await _load_group_enriched(group_id)


@api_router.get("/groups/by-code/{code}")
async def get_group_by_code(code: str):
    group = await db.groups.find_one({"code": code}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    return await _load_group_enriched(group["id"])


@api_router.post("/groups/{group_id}/join")
async def join_group(group_id: str, body: JoinGroupIn):
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("is_blocked"):
        raise HTTPException(403, "This group has been blocked by an administrator.")
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    if user.get("is_blocked"):
        raise HTTPException(403, "Your account has been blocked. Please contact support.")
    members = group.get("members", [])
    if not any(m["user_id"] == body.user_id for m in members):
        members.append({"user_id": body.user_id, "role": "member", "joined_at": now_iso()})
        await db.groups.update_one({"id": group_id}, {"$set": {"members": members}})
    return await _load_group_enriched(group_id)



@api_router.patch("/groups/{group_id}")
async def update_group_meta(group_id: str, body: UpdateGroupMetaIn):
    """Lead-only: update bill title, tax, or tip after creation.

    Title can be edited until all contributions are complete (derived_status='contributed' or beyond).
    Tax/tip can only be edited while status='open' (no merchant payment yet).
    """
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group["lead_id"] != body.user_id:
        raise HTTPException(403, "Only the lead can edit the bill")

    update_fields: dict = {}
    enriched_now = await _recompute_group(group)
    derived = enriched_now["derived_status"]

    if body.title is not None:
        # Allow title edit until all contributions complete
        if derived in ("contributed", "repaying", "settled") or group.get("status") != "open":
            raise HTTPException(400, "Title is locked once all contributions are complete.")
        title = body.title.strip()
        if not title:
            raise HTTPException(400, "Title cannot be empty")
        update_fields["title"] = title

    if body.tax is not None or body.tip is not None:
        # Tax/tip editable only while status='open'
        if group.get("status") != "open":
            raise HTTPException(400, "Tax/tip can no longer be edited — bill has been settled.")
        new_tax = float(body.tax) if body.tax is not None else float(group.get("tax", 0))
        new_tip = float(body.tip) if body.tip is not None else float(group.get("tip", 0))
        if new_tax < 0 or new_tip < 0:
            raise HTTPException(400, "Tax/tip must be non-negative")
        update_fields["tax"] = new_tax
        update_fields["tip"] = new_tip

        # Recompute total_amount = subtotal (sum items) + new tax + tip
        subtotal = sum(it["price"] * it.get("quantity", 1) for it in group.get("items", []))
        if subtotal <= 0 and group.get("split_mode") == "fast":
            # fast split with no items: keep original total_amount but adjust by delta
            old_tax = float(group.get("tax", 0))
            old_tip = float(group.get("tip", 0))
            current_total = float(group.get("total_amount", 0))
            new_total = current_total - old_tax - old_tip + new_tax + new_tip
            update_fields["total_amount"] = round(max(0.0, new_total), 2)
        else:
            update_fields["total_amount"] = round(subtotal + new_tax + new_tip, 2)

    if not update_fields:
        return await _load_group_enriched(group_id)

    await db.groups.update_one({"id": group_id}, {"$set": update_fields})
    return await _load_group_enriched(group_id)



@api_router.put("/groups/{group_id}/items")
async def update_items(group_id: str, body: UpdateItemsIn):
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("contributions"):
        raise HTTPException(
            400,
            "Items can no longer be replaced — contributions already started. Add new items instead.",
        )
    items = [
        {"id": new_id("it_"), "name": it.name, "price": it.price, "quantity": it.quantity}
        for it in body.items
    ]
    await db.groups.update_one(
        {"id": group_id}, {"$set": {"items": items, "assignments": []}}
    )
    return await _load_group_enriched(group_id)


@api_router.post("/groups/{group_id}/items/append")
async def append_items(group_id: str, body: AppendItemsIn):
    """Lead-only: add new items to an existing group, preserving existing items + assignments."""
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group["lead_id"] != body.user_id:
        raise HTTPException(403, "Only lead can add items")
    if group.get("status") != "open":
        raise HTTPException(400, "Bill is settled — items can no longer be added.")
    new_items = [
        {"id": new_id("it_"), "name": it.name, "price": it.price, "quantity": it.quantity}
        for it in body.items
    ]
    items = (group.get("items") or []) + new_items
    # Bump total_amount to include the new items' subtotal so funding logic stays accurate
    extra = sum(it["price"] * it["quantity"] for it in new_items)
    new_total = round(float(group.get("total_amount") or 0) + extra, 2)
    update_doc = {"items": items, "total_amount": new_total}
    # If group was already 'paid' (group-funded) but new items push it back into shortfall,
    # let the lead know via the funding recompute. We don't auto-revert status.
    await db.groups.update_one({"id": group_id}, {"$set": update_doc})
    return await _load_group_enriched(group_id)


@api_router.delete("/groups/{group_id}/items/{item_id}")
async def delete_item(group_id: str, item_id: str, user_id: str):
    """Lead-only: remove an item from the bill. Blocked once any contribution exists."""
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group["lead_id"] != user_id:
        raise HTTPException(403, "Only lead can delete items")
    if group.get("status") == "closed":
        raise HTTPException(400, "Group is closed")
    if group.get("contributions"):
        raise HTTPException(
            400,
            "Items can no longer be deleted — contributions already started.",
        )
    items = group.get("items") or []
    target = next((i for i in items if i["id"] == item_id), None)
    if not target:
        raise HTTPException(404, "Item not found")
    new_items = [i for i in items if i["id"] != item_id]
    new_assignments = [a for a in (group.get("assignments") or []) if a["item_id"] != item_id]
    removed = float(target["price"]) * int(target["quantity"])
    new_total = round(max(0.0, float(group.get("total_amount") or 0) - removed), 2)
    await db.groups.update_one(
        {"id": group_id},
        {"$set": {"items": new_items, "assignments": new_assignments, "total_amount": new_total}},
    )
    return await _load_group_enriched(group_id)


@api_router.patch("/groups/{group_id}/items/{item_id}")
async def patch_item(group_id: str, item_id: str, body: ItemPatchIn):
    """Lead-only: increase or decrease an item's quantity by ±1."""
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group["lead_id"] != body.user_id:
        raise HTTPException(403, "Only lead can change quantity")
    if group.get("status") == "closed":
        raise HTTPException(400, "Group is closed")
    items = group.get("items") or []
    idx = next((i for i, it in enumerate(items) if it["id"] == item_id), -1)
    if idx < 0:
        raise HTTPException(404, "Item not found")
    target = items[idx]
    new_qty = int(target["quantity"]) + int(body.quantity_delta)
    if new_qty < 1:
        raise HTTPException(400, "Quantity can't go below 1 — use delete instead")
    claimed = sum(
        int(a["quantity"]) for a in (group.get("assignments") or []) if a["item_id"] == item_id
    )
    if new_qty < claimed:
        raise HTTPException(400, f"{claimed} already claimed — reduce claims first")
    items[idx] = {**target, "quantity": new_qty}
    delta_amt = float(target["price"]) * int(body.quantity_delta)
    new_total = round(max(0.0, float(group.get("total_amount") or 0) + delta_amt), 2)
    await db.groups.update_one(
        {"id": group_id}, {"$set": {"items": items, "total_amount": new_total}}
    )
    return await _load_group_enriched(group_id)


@api_router.post("/groups/{group_id}/assign")
async def assign_item(group_id: str, body: AssignIn):
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    item = next((i for i in group.get("items", []) if i["id"] == body.item_id), None)
    if not item:
        raise HTTPException(404, "Item not found")

    assignments = group.get("assignments", [])
    # remove existing for same user+item
    assignments = [a for a in assignments if not (a["user_id"] == body.user_id and a["item_id"] == body.item_id)]

    # validate quantity not exceeding remaining
    claimed_by_others = sum(a["quantity"] for a in assignments if a["item_id"] == body.item_id)
    if body.quantity < 0:
        raise HTTPException(400, "Quantity must be >= 0")
    if claimed_by_others + body.quantity > item["quantity"]:
        raise HTTPException(400, "Quantity exceeds available")

    if body.quantity > 0:
        assignments.append({"user_id": body.user_id, "item_id": body.item_id, "quantity": body.quantity})

    await db.groups.update_one({"id": group_id}, {"$set": {"assignments": assignments}})
    return await _load_group_enriched(group_id)


@api_router.post("/groups/{group_id}/contribute")
async def contribute(group_id: str, body: ContributeIn, request: Request):
    """Member (or lead) pays their share into the group wallet via real Stripe Checkout (Phase F1).

    Flow:
      1. Server computes amount + applies user credits virtually (planned).
      2. If credits fully cover the amount → record contribution immediately, no Stripe.
      3. Else → create a Stripe Checkout Session for the cash portion, return checkout URL.
         The contribution is finalized when Stripe webhook confirms `payment_status=paid`
         (also handled by the GET /contribute/status/{session_id} polling endpoint as a safety net).
    """
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("status") != "open":
        raise HTTPException(400, "Bill already paid; use repay instead")
    if group.get("is_blocked"):
        raise HTTPException(403, "This group has been blocked by an administrator.")
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    if user.get("is_blocked"):
        raise HTTPException(403, "Your account has been blocked. Please contact support.")
    if not user.get("verified"):
        raise HTTPException(403, "Phone verification required before contributing")
    if not any(m["user_id"] == body.user_id for m in group.get("members", [])):
        raise HTTPException(403, "Not a member of this group")

    # Default: contribute the user's full share + any shortfall obligation if amount not provided
    enriched = await _recompute_group(group)
    per = next((p for p in enriched["per_user"] if p["user_id"] == body.user_id), None)
    share = per["total"] if per else 0.0
    already = per["contributed"] if per else 0.0
    shortfall_owed = per.get("shortfall_owed", 0.0) if per else 0.0
    remaining_share = max(0.0, share + shortfall_owed - already)
    amount = float(body.amount) if body.amount is not None else remaining_share
    if amount <= 0:
        raise HTTPException(400, "Nothing left to contribute")

    # ---- Estimate available credits (preview only — actual consumption happens
    # at finalize time so abandoned checkouts don't lock the user's credits).
    available_credits = 0.0
    rows = await db.credits.find({"user_id": body.user_id, "status": "active"}, {"_id": 0}).to_list(length=None)
    for r in rows:
        avail = round(float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0), 2)
        if avail > 0:
            available_credits += avail
    available_credits = round(available_credits, 2)
    credit_planned = round(min(available_credits, amount), 2)
    cash_owed = round(max(0.0, amount - credit_planned), 2)

    # ---- Path A: Credits fully cover → record contribution immediately, no Stripe.
    if cash_owed <= 0.01:
        contributions = list(group.get("contributions", []))
        contrib_id = new_id("c_")
        credit_applied, _events = await _consume_user_credits(body.user_id, amount, group_id, contrib_id)
        cash_paid = round(float(amount) - float(credit_applied), 2)
        contributions.append({
            "id": contrib_id,
            "user_id": body.user_id,
            "amount": round(amount, 2),
            "cash_paid": cash_paid,
            "credit_applied": round(float(credit_applied), 2),
            "notify_on_settled": bool(body.notify_on_settled),
            "via": "credit_only",
            "at": now_iso(),
        })
        update_doc: Dict[str, Any] = {"contributions": contributions}
        total_contributed = sum(c["amount"] for c in contributions)
        if total_contributed + 0.01 >= group.get("total_amount", 0):
            update_doc.update({
                "status": "paid",
                "funding_mode": "group",
                "lead_paid_at": now_iso(),
                "lead_shortfall": 0.0,
            })
        await db.groups.update_one({"id": group_id}, {"$set": update_doc})
        # Auto-issue Stripe Issuing card if fully funded.
        if update_doc.get("status") == "paid":
            try:
                refreshed = await db.groups.find_one({"id": group_id}, {"_id": 0})
                from issuing import issue_group_card
                await issue_group_card(db, refreshed)
            except Exception as e:
                logger.warning(f"[contribute] auto-issue card failed for {group_id}: {e}")
        result = await _load_group_enriched(group_id)
        return {"checkout_required": False, "credit_only": True, "amount": round(amount, 2),
                "credit_applied": round(float(credit_applied), 2), "group": result}

    # ---- Path B: Cash needed → create Stripe Checkout Session for `cash_owed`.
    origin = (body.origin_url or "").rstrip("/") if hasattr(body, "origin_url") else ""
    if not origin or not origin.startswith("http"):
        raise HTTPException(400, "origin_url (http(s)://...) is required when cash payment is needed")

    import stripe as _stripe_sdk
    _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY")

    success_url = f"{origin}/group/{group_id}/pay?contrib_session_id={{CHECKOUT_SESSION_ID}}"
    cancel_url = f"{origin}/group/{group_id}/pay?stripe_cancel=1"

    try:
        session = _stripe_sdk.checkout.Session.create(
            mode="payment",
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": f"KWIKPAY contribution — {group.get('title') or 'Group Bill'}"},
                    "unit_amount": int(round(cash_owed * 100)),
                },
                "quantity": 1,
            }],
            success_url=success_url,
            cancel_url=cancel_url,
            metadata={
                "group_id": group_id,
                "user_id": body.user_id,
                "kind": "group_member_contribute",
                "requested_amount": str(round(amount, 2)),
                "credit_planned": str(credit_planned),
                "cash_owed": str(cash_owed),
                "notify_on_settled": "1" if body.notify_on_settled else "0",
            },
        )
    except Exception as e:
        logger.exception(f"[stripe] member contribute checkout failed: {e}")
        raise HTTPException(502, f"Stripe error: {e}")

    tx = {
        "id": f"px_{session.id[:14]}",
        "session_id": session.id,
        "group_id": group_id,
        "user_id": body.user_id,
        "amount": cash_owed,
        "currency": "usd",
        "status": "initiated",
        "payment_status": "pending",
        "metadata": {
            "kind": "group_member_contribute",
            "requested_amount": round(amount, 2),
            "credit_planned": credit_planned,
            "cash_owed": cash_owed,
            "notify_on_settled": bool(body.notify_on_settled),
        },
        "applied": False,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.payment_transactions.insert_one(tx.copy())
    return {
        "checkout_required": True,
        "url": session.url,
        "session_id": session.id,
        "amount": round(amount, 2),
        "cash_owed": cash_owed,
        "credit_planned": credit_planned,
    }


@api_router.get("/contribute/status/{session_id}")
async def get_contribute_status(session_id: str):
    """Poll/finalize a member-contribution Stripe Checkout session.

    On `payment_status=paid` we (idempotently):
      1. Consume the user's credits (up to credit_planned).
      2. Insert the contribution record into the group.
      3. If group fully funded -> mark paid + auto-issue Stripe Issuing Card.
    """
    tx = await db.payment_transactions.find_one({"session_id": session_id}, {"_id": 0})
    if not tx:
        raise HTTPException(404, "Contribution session not found")
    if (tx.get("metadata") or {}).get("kind") != "group_member_contribute":
        raise HTTPException(400, "Not a member contribution session")
    if tx.get("applied"):
        return {
            "session_id": session_id,
            "status": tx.get("status"),
            "payment_status": tx.get("payment_status"),
            "amount_total": int(round(float(tx.get("amount") or 0) * 100)),
            "currency": tx.get("currency"),
            "applied": True,
            "group_id": tx.get("group_id"),
        }

    import stripe as _stripe_sdk
    _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY")
    try:
        s = _stripe_sdk.checkout.Session.retrieve(session_id)
    except Exception as e:
        logger.exception(f"[stripe] contribute.status retrieve failed: {e}")
        raise HTTPException(502, f"Stripe error: {e}")

    payment_status = getattr(s, "payment_status", None)
    sess_status = getattr(s, "status", None)
    update: dict = {"status": sess_status, "payment_status": payment_status, "updated_at": now_iso()}

    if payment_status == "paid" and not tx.get("applied"):
        meta = tx.get("metadata") or {}
        group_id = tx["group_id"]
        user_id = tx["user_id"]
        cash_owed = float(meta.get("cash_owed") or tx.get("amount") or 0)
        credit_planned = float(meta.get("credit_planned") or 0)
        requested_amount = float(meta.get("requested_amount") or (cash_owed + credit_planned))

        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if group and group.get("status") == "open":
            contributions = list(group.get("contributions") or [])
            contrib_id = new_id("c_")
            credit_consumed, _events = await _consume_user_credits(
                user_id, credit_planned, group_id, contrib_id
            ) if credit_planned > 0 else (0.0, [])
            actual_amount = round(cash_owed + float(credit_consumed), 2)
            contributions.append({
                "id": contrib_id,
                "user_id": user_id,
                "amount": actual_amount,
                "cash_paid": round(cash_owed, 2),
                "credit_applied": round(float(credit_consumed), 2),
                "notify_on_settled": bool(meta.get("notify_on_settled")),
                "via": "stripe",
                "stripe_session_id": session_id,
                "at": now_iso(),
            })
            update_doc: Dict[str, Any] = {"contributions": contributions}
            total_contributed = sum(c["amount"] for c in contributions)
            if total_contributed + 0.01 >= float(group.get("total_amount") or 0):
                update_doc.update({
                    "status": "paid",
                    "funding_mode": "group",
                    "lead_paid_at": now_iso(),
                    "lead_shortfall": 0.0,
                })
            await db.groups.update_one({"id": group_id}, {"$set": update_doc})

            # Auto-issue Stripe Issuing card if fully funded
            if update_doc.get("status") == "paid":
                try:
                    refreshed = await db.groups.find_one({"id": group_id}, {"_id": 0})
                    from issuing import issue_group_card
                    await issue_group_card(db, refreshed)
                except Exception as e:
                    logger.warning(f"[contribute.status] auto-issue card failed for {group_id}: {e}")

        update["applied"] = True

    await db.payment_transactions.update_one({"session_id": session_id}, {"$set": update})
    return {
        "session_id": session_id,
        "status": sess_status,
        "payment_status": payment_status,
        "amount_total": getattr(s, "amount_total", None),
        "currency": getattr(s, "currency", None),
        "applied": bool(update.get("applied") or tx.get("applied")),
        "group_id": tx.get("group_id"),
    }



@api_router.post("/groups/{group_id}/pay")
async def pay_group(group_id: str, body: PayIn):
    """Lead settles the bill with the merchant. Requires lead to have contributed
    their own share first; remaining shortfall is handled per `shortfall_mode`."""
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group["lead_id"] != body.user_id:
        raise HTTPException(403, "Only lead can pay the merchant")
    if group.get("status") != "open":
        raise HTTPException(400, "Bill already paid")
    if group.get("is_blocked"):
        raise HTTPException(403, "This group has been blocked by an administrator.")
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user or not user.get("verified"):
        raise HTTPException(403, "Lead must verify phone before paying")
    if user.get("is_blocked"):
        raise HTTPException(403, "Your account has been blocked. Please contact support.")

    enriched = await _recompute_group(group)
    lead_per = next((p for p in enriched["per_user"] if p["user_id"] == body.user_id), None)
    if lead_per and lead_per["contributed"] + 0.01 < lead_per["total"]:
        raise HTTPException(
            400,
            f"Please contribute your own share first (${lead_per['total'] - lead_per['contributed']:.2f}).",
        )

    contributions = list(group.get("contributions", []))
    # IMPORTANT: shortfall obligations + notifications are RESET on each /pay call,
    # so changing the shortfall mode replaces (not stacks) the previous assignment.
    obligations = [
        o for o in (group.get("shortfall_obligations") or [])
        if o.get("kind") not in ("shortfall_member", "shortfall_split")
    ]
    notifications = [
        n for n in (group.get("notifications") or [])
        if n.get("kind") not in ("shortfall_assigned", "shortfall_lead_covered")
    ]
    total_contributed = sum(float(c["amount"]) for c in contributions)
    total = float(group.get("total_amount") or 0.0)
    shortfall = round(max(0.0, total - total_contributed), 2)

    settlement: Optional[dict] = None
    awaiting_obligations = False
    if shortfall > 0.01:
        mode = body.shortfall_mode
        if not mode:
            raise HTTPException(
                400,
                f"Bill is short ${shortfall:.2f}. Choose how to settle the shortfall.",
            )
        is_loan = bool(body.is_loan) if body.is_loan is not None else True

        # Determine beneficiaries: members who still owe (outstanding > 0)
        beneficiaries = [
            p["user_id"] for p in enriched["per_user"]
            if p["outstanding"] > 0.01 and p["user_id"] != group["lead_id"]
        ]

        if mode == "lead":
            # Lead fronts the cash → wallet immediately funded → merchant paid now.
            funder_id = group["lead_id"]
            contributions.append({
                "id": new_id("c_"),
                "user_id": funder_id,
                "amount": shortfall,
                "is_shortfall": True,
                "is_loan": is_loan,
                "covers": beneficiaries,
                "at": now_iso(),
            })
            # Notify each beneficiary of the lead's coverage
            for bid in beneficiaries:
                msg = (
                    f"Lead covered ${shortfall:.2f} shortfall on your behalf — please repay."
                    if is_loan
                    else f"Lead covered the ${shortfall:.2f} shortfall as a gift — no repayment needed."
                )
                notifications.append({
                    "id": new_id("n_"),
                    "user_id": bid,
                    "kind": "shortfall_lead_covered",
                    "amount": shortfall,
                    "message": msg,
                    "at": now_iso(),
                    "delivered_via": "sms_mock",
                })
        elif mode == "member":
            # Assign shortfall as an OBLIGATION on the chosen member. Don't pay merchant yet.
            if not body.funder_member_id:
                raise HTTPException(400, "funder_member_id required for member mode")
            funder_id = body.funder_member_id
            if not any(m["user_id"] == funder_id for m in group.get("members", [])):
                raise HTTPException(400, "Funder is not a member")
            obligations.append({
                "id": new_id("o_"),
                "user_id": funder_id,
                "amount": shortfall,
                "kind": "shortfall_member",
                "covers": [b for b in beneficiaries if b != funder_id],
                "at": now_iso(),
            })
            notifications.append({
                "id": new_id("n_"),
                "user_id": funder_id,
                "kind": "shortfall_assigned",
                "amount": shortfall,
                "message": f"You've been asked to cover a ${shortfall:.2f} shortfall on the bill.",
                "at": now_iso(),
                "delivered_via": "sms_mock",
            })
            awaiting_obligations = True
        elif mode == "split_equal":
            # Distribute obligations equally across ALL members (including lead). Don't pay merchant yet.
            split_targets = [m["user_id"] for m in group.get("members", [])]
            if not split_targets:
                raise HTTPException(400, "No members to split shortfall across")
            per_share = round(shortfall / len(split_targets), 2)
            # Adjust last share for rounding
            assigned = 0.0
            for idx, uid in enumerate(split_targets):
                amt = per_share if idx < len(split_targets) - 1 else round(shortfall - assigned, 2)
                assigned += amt
                obligations.append({
                    "id": new_id("o_"),
                    "user_id": uid,
                    "amount": amt,
                    "kind": "shortfall_split",
                    "covers": beneficiaries,
                    "at": now_iso(),
                })
                notifications.append({
                    "id": new_id("n_"),
                    "user_id": uid,
                    "kind": "shortfall_assigned",
                    "amount": amt,
                    "message": f"Bill is short — your share of the shortfall is ${amt:.2f}.",
                    "at": now_iso(),
                    "delivered_via": "sms_mock",
                })
            is_loan = True  # split obligations are always paid back (not a gift)
            awaiting_obligations = True
        else:
            raise HTTPException(400, "Invalid shortfall_mode")

        settlement = {
            "mode": mode,
            "is_loan": is_loan,
            "amount": shortfall,
            "beneficiaries": beneficiaries,
            "at": now_iso(),
        }
        if mode in ("lead", "member"):
            settlement["funder_id"] = funder_id

    # If shortfall mode is member/split_equal: merchant payment is deferred.
    # We persist the obligations + notifications and keep status='open' (awaiting shortfall payments).
    if awaiting_obligations:
        update_doc = {
            "shortfall_obligations": obligations,
            "notifications": notifications,
            "shortfall_settlement": settlement,
        }
        await db.groups.update_one({"id": group_id}, {"$set": update_doc})
        return await _load_group_enriched(group_id)

    others_contributed = any(c["user_id"] != group["lead_id"] for c in group.get("contributions", []))
    if shortfall <= 0.01:
        funding_mode = "group"
    elif others_contributed:
        funding_mode = "shortfall"
    else:
        funding_mode = "lead"

    update_doc = {
        "status": "paid",
        "funding_mode": funding_mode,
        "lead_paid_at": now_iso(),
        "lead_shortfall": shortfall,
        "contributions": contributions,
        "shortfall_obligations": obligations,
        "notifications": notifications,
    }
    if settlement:
        update_doc["shortfall_settlement"] = settlement

    await db.groups.update_one({"id": group_id}, {"$set": update_doc})

    # If gift mode (lead absorbed shortfall as gift), group is fully settled.
    if settlement and not settlement["is_loan"]:
        await db.groups.update_one({"id": group_id}, {"$set": {"status": "closed"}})

    return await _load_group_enriched(group_id)


@api_router.post("/groups/{group_id}/repay")
async def repay(group_id: str, body: RepayIn):
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("status") == "open":
        raise HTTPException(400, "Bill not yet settled with merchant; use contribute instead")
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    if not user.get("verified"):
        raise HTTPException(403, "Phone verification required before payment")

    enriched = await _recompute_group(group)
    per = next((p for p in enriched["per_user"] if p["user_id"] == body.user_id), None)
    if not per:
        raise HTTPException(403, "Not a member of this group")
    if per["outstanding"] <= 0.01:
        raise HTTPException(400, "Nothing to repay")
    if body.amount > per["outstanding"] + 0.01:
        raise HTTPException(400, f"Amount exceeds outstanding ${per['outstanding']:.2f}")

    repayments = group.get("repayments", [])
    repayments.append({"id": new_id("r_"), "user_id": body.user_id, "amount": round(body.amount, 2), "at": now_iso()})
    await db.groups.update_one({"id": group_id}, {"$set": {"repayments": repayments}})

    # Auto-close when fully settled
    enriched = await _load_group_enriched(group_id)
    all_settled = all(p["outstanding"] <= 0.01 for p in enriched["per_user"] if p["user_id"] != group["lead_id"])
    if all_settled:
        await db.groups.update_one({"id": group_id}, {"$set": {"status": "closed"}})
        enriched = await _load_group_enriched(group_id)
    return enriched


@api_router.get("/users/{user_id}/groups")
async def get_user_groups(user_id: str):
    groups = await db.groups.find(
        {"members.user_id": user_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(100)
    enriched = []
    for g in groups:
        e = await _recompute_group(g)
        # minimal projection
        enriched.append({
            "id": g["id"],
            "title": g["title"],
            "total": e["total"],
            "status": g["status"],
            "derived_status": e["derived_status"],
            "lead_id": g["lead_id"],
            "created_at": g["created_at"],
            "member_count": len(g.get("members", [])),
        })
    return enriched


# ------------- Referrals (Phase C1) -------------

@api_router.get("/users/{user_id}/referrals")
async def get_user_referrals(user_id: str):
    """Referral summary for a user: their code, who referred them, who they referred."""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    # Backfill missing code so existing users instantly get one when they open the screen
    if not user.get("referral_code"):
        code = await generate_unique_referral_code(db)
        await db.users.update_one({"id": user_id}, {"$set": {"referral_code": code}})
        user["referral_code"] = code

    referrer = None
    if user.get("referred_by_user_id"):
        ref = await db.users.find_one(
            {"id": user["referred_by_user_id"]}, {"_id": 0, "id": 1, "name": 1, "referral_code": 1}
        )
        if ref:
            referrer = {"id": ref["id"], "name": ref.get("name"), "code": ref.get("referral_code")}

    referees_cursor = db.users.find(
        {"referred_by_user_id": user_id},
        {"_id": 0, "id": 1, "name": 1, "verified": 1, "created_at": 1, "phone": 1},
    ).sort("created_at", -1)
    referees = await referees_cursor.to_list(length=None)
    # Mask phone for privacy: keep last 4 digits only.
    for r in referees:
        if r.get("phone"):
            ph = r["phone"]
            r["phone"] = ("*" * max(0, len(ph) - 4)) + ph[-4:] if len(ph) > 4 else ph

    settings = await _get_referral_settings()
    pending = await db.credits.count_documents({"user_id": user_id, "status": "pending"})
    return {
        "user_id": user_id,
        "referral_code": user.get("referral_code"),
        "referred_by": referrer,
        "referees_count": len(referees),
        "verified_referees_count": sum(1 for r in referees if r.get("verified")),
        "referees": referees,
        "settings": {
            "enabled": bool(settings.get("enabled")),
            "referrer_credit": float(settings.get("referrer_credit") or 0),
            "referee_credit": float(settings.get("referee_credit") or 0),
        },
        "pending_credits": pending,
    }


@api_router.get("/referrals/lookup/{code}")
async def referral_lookup(code: str):
    """Public-ish: look up the referrer by code so the signup screen can show
    "You're being invited by Alice" without exposing personal data."""
    rc = (code or "").strip().upper()
    if not rc:
        raise HTTPException(400, "Code required")
    referrer = await db.users.find_one(
        {"referral_code": rc, "is_blocked": {"$ne": True}},
        {"_id": 0, "id": 1, "name": 1, "referral_code": 1},
    )
    if not referrer:
        raise HTTPException(404, "Referral code not found")
    settings = await _get_referral_settings()
    return {
        "valid": True,
        "referrer_name": referrer["name"],
        "referrer_code": referrer["referral_code"],
        "settings": {
            "enabled": bool(settings.get("enabled")),
            "referee_credit": float(settings.get("referee_credit") or 0),
        },
    }


# ------------- Credits & discounts (Phase C2) -------------

@api_router.get("/users/{user_id}/credits")
async def get_user_credits(user_id: str):
    """User wallet: balance + recent ledger rows + lead auto-discount info."""
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    rows = await db.credits.find(
        {"user_id": user_id}, {"_id": 0}
    ).sort("created_at", -1).limit(50).to_list(length=None)
    balance = await _user_credit_balance(user_id)
    items = []
    for r in rows:
        items.append({
            "id": r.get("id"),
            "amount": float(r.get("amount") or 0),
            "consumed_amount": float(r.get("consumed_amount") or 0),
            "remaining": round(float(r.get("amount") or 0) - float(r.get("consumed_amount") or 0), 2),
            "kind": r.get("kind"),
            "status": r.get("status"),
            "note": r.get("note"),
            "created_at": r.get("created_at"),
            "last_consumed_at": r.get("last_consumed_at"),
        })
    return {
        "user_id": user_id,
        "balance": balance,
        "items": items,
        "lead_auto_discount": user.get("lead_auto_discount"),
    }



# ------------- Receipt OCR -------------

@api_router.post("/receipt/scan")
async def scan_receipt(body: ScanReceiptIn):
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
    except Exception as e:
        raise HTTPException(500, f"Emergent integrations not available: {e}")

    api_key = os.environ.get("EMERGENT_LLM_KEY")
    if not api_key:
        raise HTTPException(500, "EMERGENT_LLM_KEY not configured")

    system_msg = (
        "You are a receipt parser. Extract line items and totals from restaurant receipts. "
        "Return STRICT JSON only, no prose. Schema: "
        '{"items":[{"name":string,"price":number,"quantity":number}],"tax":number,"tip":number,"total":number}. '
        "All amounts are unit price in dollars (not total of line). If unsure, set quantity=1. "
        "If tax/tip not visible, set 0."
    )
    chat = LlmChat(api_key=api_key, session_id=new_id("ocr_"), system_message=system_msg).with_model("openai", "gpt-4o")
    # Strip data URL prefix if present
    b64 = body.image_base64
    if b64.startswith("data:"):
        b64 = b64.split(",", 1)[1]
    msg = UserMessage(
        text="Parse this receipt. Return only JSON.",
        file_contents=[ImageContent(image_base64=b64)],
    )
    try:
        response = await chat.send_message(msg)
    except Exception as e:
        raise HTTPException(502, f"OCR failed: {e}")

    text = response if isinstance(response, str) else str(response)
    # Try to extract JSON
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        raise HTTPException(422, "Could not parse receipt JSON")
    try:
        data = json.loads(match.group(0))
    except Exception:
        raise HTTPException(422, "Invalid JSON from OCR")
    # Normalize
    items = []
    for it in data.get("items", []) or []:
        try:
            items.append({
                "name": str(it.get("name", "Item")),
                "price": float(it.get("price", 0) or 0),
                "quantity": int(it.get("quantity", 1) or 1),
            })
        except Exception:
            continue
    return {
        "items": items,
        "tax": float(data.get("tax", 0) or 0),
        "tip": float(data.get("tip", 0) or 0),
        "total": float(data.get("total", 0) or 0),
    }


# ------------- Health -------------

@api_router.get("/")
async def root():
    return {"message": "GroupPay API", "ok": True}


from admin_routes import build_admin_router  # noqa: E402

api_router.include_router(build_admin_router(db))

# Phase E: Stripe Checkout payment routes (attach before app.include_router)
try:
    from payments import attach_payment_routes  # noqa: E402
    attach_payment_routes(api_router, db)
except Exception as _e:
    print("[startup] payment routes attach failed:", _e)

app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
async def _seed_admins():
    from admin import ensure_seed_admin
    try:
        await ensure_seed_admin(db)
    except Exception as e:
        print("[startup] seed admin failed:", e)
    # Phase C2: activate any pending credits left from C1
    try:
        await _activate_pending_credits()
    except Exception as e:
        print("[startup] activate credits failed:", e)
    # Phase D: start reminder background loop
    try:
        from reminders import start_reminder_loop
        start_reminder_loop(db, interval_seconds=900)
    except Exception as e:
        print("[startup] reminder loop failed:", e)
    # Phase E: mount Stripe payment routes
    try:
        from payments import attach_payment_routes
        attach_payment_routes(api_router, db)
        # Re-include router so new routes are registered
        # (FastAPI doesn't allow remount; instead we attach BEFORE first include)
    except Exception as e:
        print("[startup] payment routes attach failed:", e)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
