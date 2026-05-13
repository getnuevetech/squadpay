"""Payout routes — Lead cash-out via Astra OAuth (Phase 5a + 5b backend, revised).

Flow (lead-only cash-out, post-group-funded):

  1. Frontend calls POST /api/payout/authorize-url with the user's redirect URI.
     Backend returns an Astra OAuth authorize URL the WebView loads.

  2. After consent Astra redirects to the redirect URI with ?code=...&state=...
     Frontend captures the deep-link and POSTs /api/payout/oauth-callback
     with {code, state}.  Backend:
       • exchanges code → access_token + refresh_token (Astra OAuth)
       • encrypts and persists in db.astra_user_tokens (per user)
       • fetches the user's linked cards (GET /v1/cards), persists them
         in db.astra_user_cards

  3. Frontend calls GET /api/payout/cards (server-side card list).

  4. Frontend calls POST /api/payout/push-to-card with the chosen card_id
     and amount.  Backend:
       • verifies session, lead-of-group, sufficient available balance
       • posts to Astra POST /v1/transfers using the user's access_token
       • writes 3 ledger rows (payout.requested / processor_fee / settled)

  5. Astra POST /api/webhook/astra updates payout status async.

We never see raw PAN. Astra hosts all card UX; we get card_id + brand + last4.

Token storage: per-user access_token + refresh_token are encrypted at rest
using the existing crypto_kms helpers (encrypt_secret / decrypt_secret).
"""
from __future__ import annotations
import logging
import secrets
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from adapters.registry import get_payout_adapter
from adapters.payout_astra import AstraPayoutAdapter
from ledger import make_txn_id, record_payout_event, to_cents, from_cents
from core import now_iso

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────
class AuthorizeUrlIn(BaseModel):
    user_id: str
    session_id: str
    redirect_uri: str = Field(..., description="Deep link Astra redirects back to with ?code&state")
    group_id: Optional[str] = None


class OAuthCallbackIn(BaseModel):
    user_id: str
    session_id: str
    code: str
    state: str
    redirect_uri: str = Field(..., description="MUST match the redirect_uri used when getting the authorize URL")


class PushToCardIn(BaseModel):
    user_id: str
    session_id: str
    group_id: str
    card_id: str
    amount: float = Field(..., gt=0)


# ─────────────────────────────────────────────────────────────────────────────
# Auth helper (session-based, mirrors check-session)
# ─────────────────────────────────────────────────────────────────────────────
async def _require_session(db, user_id: str, session_id: str) -> dict:
    user = await db.users.find_one({"id": user_id}, {"_id": 0})
    if not user:
        raise HTTPException(401, "User not found")
    if user.get("deleted_at"):
        raise HTTPException(401, "Account no longer active")
    current = user.get("current_session_id")
    if not current or current != session_id:
        raise HTTPException(401, "Session expired — please sign in again")
    return user


# ─────────────────────────────────────────────────────────────────────────────
# Balance helper
# ─────────────────────────────────────────────────────────────────────────────
async def _lead_available_cents(db, *, group_id: str, lead_id: str) -> int:
    group = await db.groups.find_one({"id": group_id}, {"_id": 0})
    if not group:
        raise HTTPException(404, "Group not found")
    if group.get("lead_id") != lead_id:
        raise HTTPException(403, "Only the lead may cash out from this group")
    if group.get("status") != "paid":
        raise HTTPException(409, "Group is not yet fully paid")
    if (group.get("funding_mode") or "lead") != "group":
        raise HTTPException(409, "Cash-out is only available for member-funded squads")
    pipeline = [
        {"$match": {"bill_id": group_id, "account": "merchant_payable"}},
        {"$group": {"_id": "$direction", "amount_cents": {"$sum": "$amount_cents"}}},
    ]
    credit_cents = 0
    debit_cents = 0
    async for d in db.ledger_entries.aggregate(pipeline):
        if d["_id"] == "credit":
            credit_cents = int(d["amount_cents"])
        elif d["_id"] == "debit":
            debit_cents = int(d["amount_cents"])
    return max(credit_cents - debit_cents, 0)


# ─────────────────────────────────────────────────────────────────────────────
# Astra user-token helpers (encrypted at rest)
# ─────────────────────────────────────────────────────────────────────────────

def _encrypt(plain: str) -> str:
    from integrations import encrypt_secret
    return encrypt_secret(plain or "")


def _decrypt(enc: str) -> str:
    from integrations import decrypt_secret
    return decrypt_secret(enc or "")


async def _save_user_tokens(db, user_id: str, gateway: str, token_resp: dict) -> dict:
    expires_in = float(token_resp.get("expires_in") or 3600)
    doc = {
        "id": f"aut_{secrets.token_hex(8)}",
        "user_id": user_id,
        "gateway_slug": gateway,
        "access_token_enc": _encrypt(token_resp.get("access_token") or ""),
        "refresh_token_enc": _encrypt(token_resp.get("refresh_token") or ""),
        "token_type": token_resp.get("token_type") or "Bearer",
        "scope": token_resp.get("scope") or "",
        "expires_at": time.time() + expires_in,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    # Replace any existing token doc for this (user, gateway) — Astra issues one per consent
    await db.astra_user_tokens.update_one(
        {"user_id": user_id, "gateway_slug": gateway},
        {"$set": doc},
        upsert=True,
    )
    return doc


async def _load_user_access_token(db, user_id: str, gateway: str) -> Optional[str]:
    doc = await db.astra_user_tokens.find_one({"user_id": user_id, "gateway_slug": gateway}, {"_id": 0})
    if not doc:
        return None
    return _decrypt(doc.get("access_token_enc") or "")


async def _sync_user_cards(db, user_id: str, adapter: AstraPayoutAdapter, access_token: str) -> list:
    """Pull the user's linked cards from Astra and upsert them into db.astra_user_cards."""
    cards = await adapter.list_user_cards(access_token=access_token)
    out = []
    if not cards:
        # Mark all existing cards inactive (user removed them on Astra's side)
        await db.astra_user_cards.update_many({"user_id": user_id}, {"$set": {"is_active": False}})
        return out
    seen_ids = set()
    for c in cards:
        card_id = c.get("id") or c.get("card_id")
        if not card_id:
            continue
        seen_ids.add(card_id)
        doc = {
            "id": card_id,
            "user_id": user_id,
            "brand": c.get("brand") or c.get("network"),
            "last4": c.get("last4") or c.get("last_four"),
            "display_name": c.get("name") or c.get("display_name"),
            "is_active": True,
            "raw": c,
            "updated_at": now_iso(),
        }
        await db.astra_user_cards.update_one(
            {"id": card_id, "user_id": user_id},
            {"$set": doc, "$setOnInsert": {"created_at": now_iso(), "is_default": False}},
            upsert=True,
        )
        out.append({k: v for k, v in doc.items() if k != "raw"})
    # Cards no longer in Astra → mark inactive
    await db.astra_user_cards.update_many(
        {"user_id": user_id, "id": {"$nin": list(seen_ids)}},
        {"$set": {"is_active": False}},
    )
    # If no default set among active, make the first active one default
    has_default = await db.astra_user_cards.find_one(
        {"user_id": user_id, "is_default": True, "is_active": True}
    )
    if not has_default and out:
        await db.astra_user_cards.update_one(
            {"id": out[0]["id"], "user_id": user_id}, {"$set": {"is_default": True}}
        )
        out[0]["is_default"] = True
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
def attach_payout_routes(api_router: APIRouter, db):

    @api_router.post("/payout/authorize-url")
    async def authorize_url(body: AuthorizeUrlIn):
        """Generate an Astra OAuth authorize URL for the user to consent in a WebView."""
        await _require_session(db, body.user_id, body.session_id)
        adapter = await get_payout_adapter(db)
        if adapter.slug != "astra":
            raise HTTPException(503, f"Active payout provider is '{adapter.slug}', not Astra")
        state = secrets.token_urlsafe(24)
        # Persist state for CSRF-style verification
        await db.astra_oauth_states.insert_one({
            "state": state,
            "user_id": body.user_id,
            "group_id": body.group_id,
            "redirect_uri": body.redirect_uri,
            "created_at": now_iso(),
            "consumed": False,
        })
        url = adapter.build_authorize_url(redirect_uri=body.redirect_uri, state=state)
        return {
            "url": url,
            "state": state,
            "gateway_slug": "astra",
            "environment": adapter.environment,
        }

    @api_router.post("/payout/oauth-callback")
    async def oauth_callback(body: OAuthCallbackIn):
        await _require_session(db, body.user_id, body.session_id)
        # Verify state belongs to this user
        st = await db.astra_oauth_states.find_one({"state": body.state}, {"_id": 0})
        if not st or st.get("user_id") != body.user_id:
            raise HTTPException(400, "Invalid or expired OAuth state")
        if st.get("consumed"):
            raise HTTPException(409, "OAuth state already used")
        # Mark consumed atomically
        upd = await db.astra_oauth_states.update_one(
            {"state": body.state, "consumed": False}, {"$set": {"consumed": True, "consumed_at": now_iso()}}
        )
        if upd.modified_count == 0:
            raise HTTPException(409, "OAuth state already used")

        adapter = await get_payout_adapter(db)
        if adapter.slug != "astra":
            raise HTTPException(503, f"Active payout provider is '{adapter.slug}', not Astra")
        token_resp = await adapter.exchange_authorization_code(
            code=body.code, redirect_uri=body.redirect_uri
        )
        await _save_user_tokens(db, body.user_id, "astra", token_resp)

        access_token = token_resp.get("access_token") or ""
        try:
            cards = await _sync_user_cards(db, body.user_id, adapter, access_token)
        except HTTPException as he:
            # Tokens saved but card sync failed — caller can retry GET /payout/cards
            logger.warning(f"[astra] card sync after consent failed: {he.detail}")
            cards = []
        return {
            "ok": True,
            "cards": cards,
            "scope": token_resp.get("scope"),
        }

    @api_router.get("/payout/cards")
    async def list_cards(user_id: str, session_id: str, refresh: bool = False):
        await _require_session(db, user_id, session_id)
        if refresh:
            adapter = await get_payout_adapter(db)
            if adapter.slug == "astra":
                access_token = await _load_user_access_token(db, user_id, "astra")
                if access_token:
                    try:
                        await _sync_user_cards(db, user_id, adapter, access_token)
                    except Exception as e:
                        logger.warning(f"[astra] refresh cards failed: {e}")
        rows = await db.astra_user_cards.find(
            {"user_id": user_id, "is_active": True}, {"_id": 0, "raw": 0}
        ).sort("created_at", -1).to_list(length=20)
        return {"items": rows}

    @api_router.post("/payout/push-to-card")
    async def push_to_card(body: PushToCardIn):
        await _require_session(db, body.user_id, body.session_id)
        available_cents = await _lead_available_cents(
            db, group_id=body.group_id, lead_id=body.user_id
        )
        requested_cents = to_cents(body.amount)
        if requested_cents > available_cents:
            raise HTTPException(
                409,
                f"Requested ${body.amount:.2f} exceeds available cash-out balance ${from_cents(available_cents):.2f}",
            )

        # Confirm chosen card belongs to user and is active
        card = await db.astra_user_cards.find_one(
            {"id": body.card_id, "user_id": body.user_id, "is_active": True}, {"_id": 0}
        )
        if not card:
            raise HTTPException(412, "Card not found or no longer active. Re-link via Astra.")

        access_token = await _load_user_access_token(db, body.user_id, "astra")
        if not access_token:
            raise HTTPException(412, "Astra session expired. Please reconnect your Astra account.")

        adapter = await get_payout_adapter(db)
        if adapter.slug != "astra":
            raise HTTPException(503, f"Active payout provider is '{adapter.slug}', not Astra")

        txn_id = make_txn_id("payout")
        try:
            result = await adapter.push_to_card(
                amount_cents=requested_cents,
                currency="usd",
                card_token=f"{access_token}|{body.card_id}",
                idempotency_key=txn_id,
                metadata={
                    "user_id": body.user_id,
                    "group_id": body.group_id,
                    "txn_id": txn_id,
                },
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.exception(f"[astra] push_to_card failed: {e}")
            raise HTTPException(502, f"Payout gateway error: {e}")

        payout_doc = {
            "id": txn_id,
            "txn_id": txn_id,
            "user_id": body.user_id,
            "group_id": body.group_id,
            "gateway_slug": adapter.slug,
            "provider_payout_id": result.provider_payout_id,
            "amount_cents": requested_cents,
            "currency": "usd",
            "status": result.status,
            "fee_cents": int(result.fee_cents or 0),
            "card_id": body.card_id,
            "card_brand": card.get("brand"),
            "card_last4": card.get("last4"),
            "ledger_posted": False,
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        await db.payouts.insert_one(payout_doc.copy())

        try:
            await record_payout_event(
                db,
                txn_id=txn_id,
                bill_id=body.group_id,
                user_id=body.user_id,
                amount_cents=requested_cents,
                currency="usd",
                reference={
                    "provider_payout_id": result.provider_payout_id,
                    "gateway_slug": adapter.slug,
                    "card_brand": card.get("brand"),
                    "card_last4": card.get("last4"),
                    "card_id": body.card_id,
                },
                provider_fee_cents=int(result.fee_cents or 0),
                kind="lead_cash_out",
            )
            await db.payouts.update_one(
                {"txn_id": txn_id},
                {"$set": {"ledger_posted": True, "ledger_posted_at": now_iso()}},
            )
        except Exception as e:
            logger.exception(f"[ledger] payout ledger write failed for txn={txn_id}: {e}")

        return {
            "txn_id": txn_id,
            "status": result.status,
            "amount": from_cents(requested_cents),
            "provider_payout_id": result.provider_payout_id,
            "card_brand": card.get("brand"),
            "card_last4": card.get("last4"),
        }

    @api_router.post("/webhook/astra")
    async def astra_webhook(request: Request):
        body_bytes = await request.body()
        sig = request.headers.get("Astra-Signature") or request.headers.get("X-Signature")
        adapter = await get_payout_adapter(db)
        if adapter.slug != "astra":
            return {"ok": True, "ignored": "astra not active"}
        try:
            evt = await adapter.verify_webhook(body_bytes, sig)
        except Exception as e:
            logger.exception(f"[astra-webhook] verify failed: {e}")
            raise HTTPException(400, f"Webhook error: {e}")
        if not evt.provider_payout_id:
            return {"ok": True, "ignored": "no-payout-id"}
        payout = await db.payouts.find_one(
            {"provider_payout_id": evt.provider_payout_id}, {"_id": 0}
        )
        if not payout:
            return {"ok": True, "ignored": "no-internal-payout"}
        status = (evt.status or "").lower()
        if status and status != payout.get("status"):
            await db.payouts.update_one(
                {"provider_payout_id": evt.provider_payout_id},
                {"$set": {"status": status, "updated_at": now_iso(),
                          "last_webhook_at": now_iso()}},
            )
        return {"ok": True, "payout_id": payout["id"], "new_status": status or payout.get("status")}

    @api_router.get("/payout/eligibility")
    async def payout_eligibility(user_id: str, session_id: str, group_id: str):
        await _require_session(db, user_id, session_id)
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        reasons = []
        eligible = True
        if group.get("lead_id") != user_id:
            reasons.append("not_lead")
            eligible = False
        if group.get("status") != "paid":
            reasons.append("group_not_paid")
            eligible = False
        if (group.get("funding_mode") or "lead") != "group":
            reasons.append("funding_mode_not_group")
            eligible = False
        available = 0
        if eligible:
            try:
                available = await _lead_available_cents(db, group_id=group_id, lead_id=user_id)
            except HTTPException as he:
                eligible = False
                reasons.append(he.detail if isinstance(he.detail, str) else "ineligible")
        # Astra account linkage
        tok = await db.astra_user_tokens.find_one({"user_id": user_id, "gateway_slug": "astra"}, {"_id": 0, "user_id": 1})
        has_astra = bool(tok)
        default_card = None
        if has_astra:
            default_card = await db.astra_user_cards.find_one(
                {"user_id": user_id, "is_active": True, "is_default": True}, {"_id": 0, "raw": 0}
            )
        return {
            "eligible": eligible,
            "reasons": reasons,
            "available_cents": available,
            "available_usd": from_cents(available),
            "astra_linked": has_astra,
            "default_card": default_card,
            "gateway_slug": "astra",
        }
