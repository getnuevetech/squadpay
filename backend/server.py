from fastapi import FastAPI, APIRouter, HTTPException
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


def clean_mongo(doc: dict) -> dict:
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


# ------------- Models -------------

class RegisterIn(BaseModel):
    name: str


class UserOut(BaseModel):
    id: str
    name: str
    phone: Optional[str] = None
    verified: bool = False
    created_at: str


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


class RepayIn(BaseModel):
    user_id: str
    amount: float


class ContributeIn(BaseModel):
    user_id: str
    amount: Optional[float] = None  # If None, contributes user's full share
    notify_on_settled: Optional[bool] = False


class AppendItemsIn(BaseModel):
    user_id: str
    items: List[ItemIn]


class ItemPatchIn(BaseModel):
    user_id: str
    quantity_delta: int


# ------------- Pricing constants -------------
TRANSACTION_FEE_RATE = 0.03  # 3% per-member surcharge
PLATFORM_FEE = 0.03  # 3 cents flat per member


def gen_virtual_card() -> dict:
    digits = "".join(secrets.choice(string.digits) for _ in range(16))
    return {
        "id": new_id("vc_"),
        "number": digits,
        "last4": digits[-4:],
        "exp_month": 12,
        "exp_year": 2028,
        "cvv": "".join(secrets.choice(string.digits) for _ in range(3)),
        "balance": 0.0,
        "currency": "USD",
        "issued_at": now_iso(),
    }


class ScanReceiptIn(BaseModel):
    image_base64: str


# ------------- Auth -------------

@api_router.post("/auth/register", response_model=UserOut)
async def register(body: RegisterIn):
    if not body.name or not body.name.strip():
        raise HTTPException(400, "Name is required")
    user = {
        "id": new_id("u_"),
        "name": body.name.strip(),
        "phone": None,
        "verified": False,
        "created_at": now_iso(),
    }
    await db.users.insert_one(user.copy())
    return UserOut(**user)


@api_router.post("/auth/send-otp")
async def send_otp(body: SendOtpIn):
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    # Mock OTP: always 123456, but store attempt
    await db.otp_codes.update_one(
        {"user_id": body.user_id},
        {"$set": {"phone": body.phone, "code": "123456", "created_at": now_iso()}},
        upsert=True,
    )
    return {"ok": True, "message": "OTP sent (mock). Use 123456", "mocked": True}


@api_router.post("/auth/verify-otp", response_model=UserOut)
async def verify_otp(body: VerifyOtpIn):
    record = await db.otp_codes.find_one({"user_id": body.user_id}, {"_id": 0})
    if not record or record.get("code") != body.code or record.get("phone") != body.phone:
        raise HTTPException(400, "Invalid OTP code")
    await db.users.update_one(
        {"id": body.user_id}, {"$set": {"phone": body.phone, "verified": True}}
    )
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
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
    gid = new_id("g_")
    code = new_short_code(8)
    items = []
    for it in body.items:
        items.append({"id": new_id("it_"), "name": it.name, "price": it.price, "quantity": it.quantity})
    group = {
        "id": gid,
        "code": code,
        "lead_id": body.lead_id,
        "title": body.title or "Group Bill",
        "total_amount": body.total_amount,
        "tax": body.tax,
        "tip": body.tip,
        "split_mode": body.split_mode,
        "status": "open",  # open | paid | closed
        "funding_mode": None,  # group | lead | shortfall
        "virtual_card": gen_virtual_card(),
        "items": items,
        "assignments": [],
        "members": [{"user_id": body.lead_id, "role": "lead", "joined_at": now_iso()}],
        "contributions": [],  # {user_id, amount, status}
        "repayments": [],  # {user_id, amount, at}
        "lead_paid_at": None,
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
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    members = group.get("members", [])
    if not any(m["user_id"] == body.user_id for m in members):
        members.append({"user_id": body.user_id, "role": "member", "joined_at": now_iso()})
        await db.groups.update_one({"id": group_id}, {"$set": {"members": members}})
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
async def contribute(group_id: str, body: ContributeIn):
    """Member (or lead) pays their share upfront into the group wallet, before merchant payment."""
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("status") != "open":
        raise HTTPException(400, "Bill already paid; use repay instead")
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
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

    contributions = group.get("contributions", [])
    contributions.append({
        "id": new_id("c_"),
        "user_id": body.user_id,
        "amount": round(amount, 2),
        "notify_on_settled": bool(body.notify_on_settled),
        "at": now_iso(),
    })
    update_doc: Dict[str, Any] = {"contributions": contributions}

    # Auto-finalize if total contributions cover the full bill
    total_contributed = sum(c["amount"] for c in contributions)
    if total_contributed + 0.01 >= group.get("total_amount", 0):
        update_doc.update({
            "status": "paid",
            "funding_mode": "group",
            "lead_paid_at": now_iso(),
            "lead_shortfall": 0.0,
        })

    await db.groups.update_one({"id": group_id}, {"$set": update_doc})
    return await _load_group_enriched(group_id)


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
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user or not user.get("verified"):
        raise HTTPException(403, "Lead must verify phone before paying")

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
            "lead_id": g["lead_id"],
            "created_at": g["created_at"],
            "member_count": len(g.get("members", [])),
        })
    return enriched


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


app.include_router(api_router)

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    client.close()
