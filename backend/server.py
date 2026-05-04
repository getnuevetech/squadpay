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


class RepayIn(BaseModel):
    user_id: str
    amount: float


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
            per_user_total = {m["user_id"]: round(equal, 2) for m in members}
            return {
                **group,
                "subtotal": round(subtotal, 2),
                "total": round(total, 2),
                "per_user": [
                    {"user_id": uid, "food": round(total / len(members), 2), "tax_tip": 0.0, "total": per_user_total[uid]}
                    for uid in per_user_total
                ],
                "unclaimed": [],
                "fully_claimed": True,
            }

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

    fully_claimed = len(unclaimed_items) == 0 and subtotal > 0
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

    return {
        **group,
        "subtotal": round(subtotal, 2),
        "total": round(total, 2),
        "per_user": per_user,
        "unclaimed": unclaimed_items,
        "fully_claimed": fully_claimed,
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
    items = [
        {"id": new_id("it_"), "name": it.name, "price": it.price, "quantity": it.quantity}
        for it in body.items
    ]
    await db.groups.update_one(
        {"id": group_id}, {"$set": {"items": items, "assignments": []}}
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


@api_router.post("/groups/{group_id}/pay")
async def pay_group(group_id: str, body: PayIn):
    """Mock: lead pays full total upfront → lead-funded mode."""
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group["lead_id"] != body.user_id:
        raise HTTPException(403, "Only lead can pay")
    await db.groups.update_one(
        {"id": group_id},
        {"$set": {
            "status": "paid",
            "funding_mode": "lead",
            "lead_paid_at": now_iso(),
        }},
    )
    return await _load_group_enriched(group_id)


@api_router.post("/groups/{group_id}/repay")
async def repay(group_id: str, body: RepayIn):
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    user = await db.users.find_one({"id": body.user_id}, {"_id": 0})
    if not user:
        raise HTTPException(404, "User not found")
    if not user.get("verified"):
        raise HTTPException(403, "Phone verification required before payment")
    repayments = group.get("repayments", [])
    repayments.append({"id": new_id("r_"), "user_id": body.user_id, "amount": body.amount, "at": now_iso()})
    await db.groups.update_one({"id": group_id}, {"$set": {"repayments": repayments}})
    # Close if fully repaid
    enriched = await _load_group_enriched(group_id)
    total_repaid = sum(r["amount"] for r in repayments)
    # Members who owe (excl lead)
    owed = sum(p["total"] for p in enriched["per_user"] if p["user_id"] != group["lead_id"])
    if total_repaid >= owed - 0.01:
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
