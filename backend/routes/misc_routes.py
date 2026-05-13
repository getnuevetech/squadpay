"""Referrals + credits + receipt OCR + misc routes (Batch B refactor)."""
import datetime as _dt
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlencode, parse_qsl

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse

from core import (
    ScanReceiptIn,
    new_id, generate_unique_referral_code,
    _get_referral_settings, _user_credit_balance,
)


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()

logger = logging.getLogger(__name__)


def attach_referrals_credits_routes(router: APIRouter, db):

    @router.get("/users/{user_id}/referrals")
    async def get_user_referrals(user_id: str):
        """Referral summary for a user."""
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
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
        for r in referees:
            if r.get("phone"):
                ph = r["phone"]
                r["phone"] = ("*" * max(0, len(ph) - 4)) + ph[-4:] if len(ph) > 4 else ph

        settings = await _get_referral_settings(db)
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

    @router.get("/referrals/lookup/{code}")
    async def referral_lookup(code: str):
        """Look up the referrer by code (signup screen banner)."""
        rc = (code or "").strip().upper()
        if not rc:
            raise HTTPException(400, "Code required")
        referrer = await db.users.find_one(
            {"referral_code": rc, "is_blocked": {"$ne": True}},
            {"_id": 0, "id": 1, "name": 1, "referral_code": 1},
        )
        if not referrer:
            raise HTTPException(404, "Referral code not found")
        settings = await _get_referral_settings(db)
        return {
            "valid": True,
            "referrer_name": referrer["name"],
            "referrer_code": referrer["referral_code"],
            "settings": {
                "enabled": bool(settings.get("enabled")),
                "referee_credit": float(settings.get("referee_credit") or 0),
            },
        }

    @router.get("/users/{user_id}/credits")
    async def get_user_credits(user_id: str):
        """User wallet: balance + recent ledger rows + lead auto-discount info."""
        user = await db.users.find_one({"id": user_id}, {"_id": 0})
        if not user:
            raise HTTPException(404, "User not found")
        rows = await db.credits.find(
            {"user_id": user_id}, {"_id": 0}
        ).sort("created_at", -1).limit(50).to_list(length=None)
        balance = await _user_credit_balance(db, user_id)
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


def attach_misc_routes(router: APIRouter, db):
    """Receipt OCR + root + app-features + Stripe native bridge."""

    # ────────────────────────────────────────────────────────────────────
    # OCR provider failover chain (Phase B item #4)
    # ────────────────────────────────────────────────────────────────────
    # Each entry maps to LlmChat.with_model("<provider>", "<model>"). When the
    # first provider errors (network, rate-limit, model returning non-JSON), we
    # automatically try the next one. Admins can reorder this chain at runtime
    # via POST /api/admin/ocr-config — the chain is persisted in
    # `db.app_config.singleton`. ENV vars give the bootstrap default.
    _OCR_DEFAULT_CHAIN = [
        {"provider": "openai", "model": "gpt-4o"},
        {"provider": "anthropic", "model": "claude-sonnet-4-5-20250929"},
        {"provider": "gemini", "model": "gemini-2.5-flash"},
    ]

    async def _get_ocr_chain():
        """Read admin-configured chain from app_config; fall back to default."""
        try:
            cfg = await db.app_config.find_one({"_id": "ocr"}) or {}
            chain = cfg.get("providers") or []
            if isinstance(chain, list) and chain:
                # Defensive: only keep entries with both keys present
                clean = [
                    {"provider": str(c.get("provider")), "model": str(c.get("model"))}
                    for c in chain
                    if isinstance(c, dict) and c.get("provider") and c.get("model")
                ]
                if clean:
                    return clean
        except Exception:
            pass
        return list(_OCR_DEFAULT_CHAIN)

    @router.post("/receipt/scan")
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
            "Rules:\n"
            "1. price = UNIT price in dollars (not the line total). If the receipt shows '2 Maker's Mark $17.50', "
            "return {name:'Maker's Mark', price:8.75, quantity:2}.\n"
            "2. Skip free modifier/option lines that show $0.00 (e.g. 'Sweet & Sour', 'Splash', 'Neat', 'Lemon Wedge'). "
            "Only return actual purchasable items.\n"
            "3. tax = SUM of EVERY tax line on the receipt — Sales Tax + Alcohol Tax + State Tax + any other tax. "
            "Combine them into a single number.\n"
            "4. tip = explicit tip line value, or 0 if not present (ignore suggested-tip helpers like 'A 20% tip would be...').\n"
            "5. total = the final amount charged at the bottom of the receipt (the 'Total' / 'Amount Due' / card-charged value).\n"
            "6. The numbers must reconcile: sum(items[i].price * items[i].quantity) + tax + tip must equal total. "
            "If they don't, double-check that you captured ALL tax lines."
        )
        b64 = body.image_base64
        if b64.startswith("data:"):
            b64 = b64.split(",", 1)[1]

        chain = await _get_ocr_chain()
        # Walk the chain. First successful parse wins. We log every attempt to
        # db.ocr_attempts so admins can see which provider actually answered.
        attempts: List[Dict[str, Any]] = []
        data = None
        response = None
        last_err: Optional[str] = None
        for idx, prov in enumerate(chain):
            sess = new_id("ocr_")
            t_start = time.time()
            try:
                chat = LlmChat(api_key=api_key, session_id=sess, system_message=system_msg).with_model(
                    prov["provider"], prov["model"]
                )
                msg = UserMessage(
                    text="Parse this receipt. Return only JSON.",
                    file_contents=[ImageContent(image_base64=b64)],
                )
                response = await chat.send_message(msg)
                text = response if isinstance(response, str) else str(response)
                match = re.search(r"\{[\s\S]*\}", text)
                if not match:
                    raise RuntimeError("model returned no JSON object")
                data = json.loads(match.group(0))
                attempts.append({
                    "provider": prov["provider"], "model": prov["model"],
                    "ok": True, "latency_ms": int((time.time() - t_start) * 1000),
                })
                break
            except Exception as e:  # pylint: disable=broad-except
                last_err = f"{type(e).__name__}: {str(e)[:240]}"
                attempts.append({
                    "provider": prov["provider"], "model": prov["model"],
                    "ok": False, "error": last_err,
                    "latency_ms": int((time.time() - t_start) * 1000),
                })
                # Keep walking — next provider in the chain takes over.
                continue

        # Fire-and-forget audit row so admins can monitor provider reliability.
        try:
            await db.ocr_attempts.insert_one({
                "id": new_id("ocrlog_"),
                "at": now_iso(),
                "chain": chain,
                "attempts": attempts,
                "succeeded": bool(data),
                "provider_used": (next((a for a in attempts if a.get("ok")), {}) or {}).get("provider"),
            })
        except Exception:
            pass

        if data is None:
            # Every provider failed — surface the last error to the client.
            raise HTTPException(502, f"OCR failed across all providers. Last error: {last_err or 'unknown'}")
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
        tax = float(data.get("tax", 0) or 0)
        tip = float(data.get("tip", 0) or 0)
        total = float(data.get("total", 0) or 0)

        # ── Reconciliation ──────────────────────────────────────────────
        # OCR models occasionally miss a tax line (e.g. an "Alcohol Tax" row
        # on top of "Sales Tax"). Whenever the printed receipt total is
        # available, force the math to add up by absorbing any leftover
        # into the tax field. This guarantees the bill the user creates
        # exactly matches what they actually paid the merchant.
        items_subtotal = round(sum(it["price"] * it["quantity"] for it in items), 2)
        if total > 0:
            implied = round(items_subtotal + tax + tip, 2)
            diff = round(total - implied, 2)
            if abs(diff) >= 0.01:
                # Anything we can't account for via items+tip we treat as
                # under-captured tax. Never let tax go negative — if `tip`
                # was over-reported, prefer trimming it back.
                if diff > 0:
                    tax = round(tax + diff, 2)
                else:
                    # Implied > printed total: shrink tip first (over-tip
                    # is more common than over-tax), then tax.
                    take_from_tip = min(tip, -diff)
                    tip = round(tip - take_from_tip, 2)
                    remaining = round(-diff - take_from_tip, 2)
                    if remaining > 0:
                        tax = round(max(0.0, tax - remaining), 2)

        return {
            "items": items,
            "tax": tax,
            "tip": tip,
            "total": total or round(items_subtotal + tax + tip, 2),
        }

    @router.get("/")
    async def root():
        return {"message": "SquadPay API", "ok": True}

    @router.get("/app-features")
    async def get_app_features():
        """Public endpoint — feature flags for the user app (no auth)."""
        rec = await db.app_settings.find_one({"key": "features"}, {"_id": 0}) or {}
        return {
            "credits_enabled": rec.get("credits_enabled", True),
            "invite_friends_enabled": rec.get("invite_friends_enabled", True),
        }

    @router.get("/checkout/native-bridge", response_class=HTMLResponse)
    async def native_bridge(session_id: str = "", dest: str = "", kind: str = "contribute", cancel: str = ""):
        """Stripe Checkout redirects here from the in-app browser; we JS-redirect to the
        Expo/native deep link so iOS/Android pops back into the app."""
        if not dest:
            return HTMLResponse("Missing dest", status_code=400)
        try:
            parsed = urlparse(dest)
            existing = dict(parse_qsl(parsed.query, keep_blank_values=True))
        except Exception:
            existing = {}
        if cancel == "1":
            existing["stripe_cancel"] = "1"
        elif kind == "contribute":
            existing["contrib_session_id"] = session_id
        else:
            existing["session_id"] = session_id
        new_query = urlencode(existing)
        final = f"{parsed.scheme}://{parsed.netloc}{parsed.path}{('?' + new_query) if new_query else ''}"
        if parsed.fragment:
            final += f"#{parsed.fragment}"
        safe_final = final.replace('"', "%22")
        html = f"""<!DOCTYPE html>
<html><head><meta charset=\"utf-8\"><title>Returning to SquadPay…</title>
<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">
<style>
  body{{font-family:-apple-system,system-ui,sans-serif;background:#0F172A;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center;padding:20px}}
  .box{{max-width:380px}} .spin{{width:42px;height:42px;border:4px solid rgba(255,255,255,0.15);border-top-color:#4F46E5;border-radius:50%;animation:s 0.9s linear infinite;margin:0 auto 18px}}
  @keyframes s{{to{{transform:rotate(360deg)}}}}
  a{{color:#A5B4FC}}
</style></head><body><div class=\"box\">
  <div class=\"spin\"></div>
  <h2>{'Cancelled' if cancel == '1' else 'Payment confirmed'}</h2>
  <p>Returning you to the SquadPay app…</p>
  <p style=\"font-size:13px;color:#94A3B8\">If nothing happens, <a href=\"{safe_final}\">tap here</a>.</p>
</div>
<script>
  (function(){{
    var url={safe_final!r};
    setTimeout(function(){{ window.location.replace(url); }}, 100);
    setTimeout(function(){{ try{{ window.location.href = url; }}catch(e){{}} }}, 600);
  }})();
</script></body></html>"""
        return HTMLResponse(html)
