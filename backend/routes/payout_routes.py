"""Payout routes — Lead cash-out flow.

Supports two payout providers via the adapter contract:
  • Stripe Connect Express + Instant Payouts  (Phase 5a default; June 2025)
  • Astra OAuth (alt provider, still wired & catalog'd)

Public surface:
  POST /api/payout/authorize-url       → onboarding/consent URL for the WebView
  POST /api/payout/sync-after-onboarding → finalize after WebView returns (optionally accepts OAuth code+state)
  GET  /api/payout/cards               → cached list of the user's linked cards
  POST /api/payout/push-to-card        → Lead cash-out
  GET  /api/payout/eligibility         → can-i-cash-out check
  POST /api/webhook/astra              → Astra webhook
  POST /api/webhook/stripe-connect     → Stripe Connect (payout.*) webhook

Eligibility (Phase 5b CTA spec):
  • Lead-of-group only
  • Group must be status=="paid" AND funding_mode=="group"
  • Available cents = sum(ledger.merchant_payable CREDIT for bill) − sum(DEBIT)
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
from adapters.payout_stripe_connect import StripeConnectPayoutAdapter
from ledger import make_txn_id, record_payout_event, to_cents, from_cents
from core import now_iso

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Request models
# ─────────────────────────────────────────────────────────────────────────────
class AuthorizeUrlIn(BaseModel):
    user_id: str
    session_id: str
    return_url: str = Field(..., description="Deep link the provider redirects back to")
    refresh_url: Optional[str] = Field(None, description="Stripe Connect: refresh URL if user bails")
    group_id: Optional[str] = None


class SyncAfterOnboardingIn(BaseModel):
    user_id: str
    session_id: str
    # Astra-only — frontend includes these from the redirect ?code=&state= params
    code: Optional[str] = None
    state: Optional[str] = None
    redirect_uri: Optional[str] = None  # Astra requires the same redirect_uri on token exchange


class PushToCardIn(BaseModel):
    user_id: str
    session_id: str
    group_id: str
    card_id: str
    amount: float = Field(..., gt=0)


# ─────────────────────────────────────────────────────────────────────────────
# Auth + balance helpers
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
# Encryption helpers
# ─────────────────────────────────────────────────────────────────────────────
def _encrypt(plain: str) -> str:
    from integrations import encrypt_secret
    return encrypt_secret(plain or "")


def _decrypt(enc: str) -> str:
    from integrations import decrypt_secret
    return decrypt_secret(enc or "")


# ─────────────────────────────────────────────────────────────────────────────
# Astra-specific token + card helpers
# ─────────────────────────────────────────────────────────────────────────────
async def _save_astra_tokens(db, user_id: str, token_resp: dict) -> None:
    expires_in = float(token_resp.get("expires_in") or 3600)
    doc = {
        "id": f"aut_{secrets.token_hex(8)}",
        "user_id": user_id,
        "gateway_slug": "astra",
        "access_token_enc": _encrypt(token_resp.get("access_token") or ""),
        "refresh_token_enc": _encrypt(token_resp.get("refresh_token") or ""),
        "token_type": token_resp.get("token_type") or "Bearer",
        "scope": token_resp.get("scope") or "",
        "expires_at": time.time() + expires_in,
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    await db.astra_user_tokens.update_one(
        {"user_id": user_id, "gateway_slug": "astra"}, {"$set": doc}, upsert=True,
    )


async def _load_astra_access_token(db, user_id: str) -> Optional[str]:
    doc = await db.astra_user_tokens.find_one({"user_id": user_id, "gateway_slug": "astra"}, {"_id": 0})
    if not doc:
        return None
    return _decrypt(doc.get("access_token_enc") or "")


# ─────────────────────────────────────────────────────────────────────────────
# Generic per-user card persistence (works for both providers)
# ─────────────────────────────────────────────────────────────────────────────
async def _upsert_user_cards(db, user_id: str, gateway: str, cards: list) -> list:
    """Persist the user's linked cards in db.payout_user_cards (one row per card).

    Marks cards not in the latest list as is_active=false.
    """
    out = []
    seen_ids = set()
    for c in cards:
        cid = c.get("id")
        if not cid:
            continue
        seen_ids.add(cid)
        doc = {
            "id": cid,
            "user_id": user_id,
            "gateway_slug": gateway,
            "brand": c.get("brand"),
            "last4": c.get("last4"),
            "exp_month": c.get("exp_month"),
            "exp_year": c.get("exp_year"),
            "currency": c.get("currency"),
            "display_name": c.get("display_name"),
            "is_active": True,
            "updated_at": now_iso(),
        }
        await db.payout_user_cards.update_one(
            {"id": cid, "user_id": user_id, "gateway_slug": gateway},
            {"$set": doc, "$setOnInsert": {
                "created_at": now_iso(),
                "is_default": bool(c.get("is_default")),
            }},
            upsert=True,
        )
        out.append({k: v for k, v in doc.items() if k != "raw"})
    # Mark cards no longer present as inactive
    await db.payout_user_cards.update_many(
        {"user_id": user_id, "gateway_slug": gateway, "id": {"$nin": list(seen_ids) or [""]}},
        {"$set": {"is_active": False}},
    )
    # Ensure at least one default if any active
    has_default = await db.payout_user_cards.find_one(
        {"user_id": user_id, "gateway_slug": gateway, "is_active": True, "is_default": True}
    )
    if not has_default and out:
        await db.payout_user_cards.update_one(
            {"id": out[0]["id"], "user_id": user_id, "gateway_slug": gateway},
            {"$set": {"is_default": True}},
        )
        out[0]["is_default"] = True
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────
def attach_payout_routes(api_router: APIRouter, db):

    @api_router.post("/payout/authorize-url")
    async def authorize_url(body: AuthorizeUrlIn):
        user = await _require_session(db, body.user_id, body.session_id)
        adapter = await get_payout_adapter(db)

        # ── Stripe Connect Express
        if isinstance(adapter, StripeConnectPayoutAdapter):
            mapping = await db.connect_user_accounts.find_one(
                {"user_id": body.user_id, "gateway_slug": "stripe_connect"}, {"_id": 0}
            )
            if not mapping:
                acct_id = await adapter.ensure_connected_account(
                    email=user.get("email"), user_id=body.user_id
                )
                await db.connect_user_accounts.insert_one({
                    "user_id": body.user_id,
                    "gateway_slug": "stripe_connect",
                    "account_id": acct_id,
                    "details_submitted": False,
                    "payouts_enabled": False,
                    "created_at": now_iso(),
                    "updated_at": now_iso(),
                })
            else:
                acct_id = mapping["account_id"]
            url = await adapter.create_account_link(
                account_id=acct_id,
                return_url=body.return_url,
                refresh_url=body.refresh_url or body.return_url,
            )
            return {
                "url": url,
                "gateway_slug": "stripe_connect",
                "account_id": acct_id,
                "kind": "account_onboarding",
            }

        # ── Astra
        if isinstance(adapter, AstraPayoutAdapter):
            state = secrets.token_urlsafe(24)
            await db.astra_oauth_states.insert_one({
                "state": state, "user_id": body.user_id, "group_id": body.group_id,
                "redirect_uri": body.return_url, "created_at": now_iso(), "consumed": False,
            })
            url = adapter.build_authorize_url(redirect_uri=body.return_url, state=state)
            return {"url": url, "state": state, "gateway_slug": "astra",
                    "environment": adapter.environment, "kind": "oauth_authorize"}

        raise HTTPException(503, f"Active payout provider '{adapter.slug}' has no onboarding flow")

    @api_router.post("/payout/sync-after-onboarding")
    async def sync_after_onboarding(body: SyncAfterOnboardingIn):
        await _require_session(db, body.user_id, body.session_id)
        adapter = await get_payout_adapter(db)

        # ── Stripe Connect: no code exchange. Retrieve account, list cards, persist.
        if isinstance(adapter, StripeConnectPayoutAdapter):
            mapping = await db.connect_user_accounts.find_one(
                {"user_id": body.user_id, "gateway_slug": "stripe_connect"}, {"_id": 0}
            )
            if not mapping:
                raise HTTPException(412, "No Stripe Connect account on file. Re-run /payout/authorize-url first.")
            acct_info = await adapter.retrieve_account(mapping["account_id"])
            await db.connect_user_accounts.update_one(
                {"user_id": body.user_id, "gateway_slug": "stripe_connect"},
                {"$set": {
                    "details_submitted": acct_info["details_submitted"],
                    "payouts_enabled": acct_info["payouts_enabled"],
                    "updated_at": now_iso(),
                }},
            )
            cards: list = []
            if acct_info["details_submitted"]:
                ext_cards = await adapter.list_external_cards(mapping["account_id"])
                cards = await _upsert_user_cards(db, body.user_id, "stripe_connect", ext_cards)
            return {
                "ok": True,
                "details_submitted": acct_info["details_submitted"],
                "payouts_enabled": acct_info["payouts_enabled"],
                "requirements_due": acct_info.get("requirements", {}).get("currently_due", []),
                "cards": cards,
            }

        # ── Astra: full OAuth code exchange
        if isinstance(adapter, AstraPayoutAdapter):
            if not body.code or not body.state or not body.redirect_uri:
                raise HTTPException(400, "Astra: code, state and redirect_uri are required")
            st = await db.astra_oauth_states.find_one({"state": body.state}, {"_id": 0})
            if not st or st.get("user_id") != body.user_id:
                raise HTTPException(400, "Invalid or expired OAuth state")
            if st.get("consumed"):
                raise HTTPException(409, "OAuth state already used")
            upd = await db.astra_oauth_states.update_one(
                {"state": body.state, "consumed": False},
                {"$set": {"consumed": True, "consumed_at": now_iso()}},
            )
            if upd.modified_count == 0:
                raise HTTPException(409, "OAuth state already used")
            token_resp = await adapter.exchange_authorization_code(
                code=body.code, redirect_uri=body.redirect_uri,
            )
            await _save_astra_tokens(db, body.user_id, token_resp)
            access_token = token_resp.get("access_token") or ""
            try:
                raw_cards = await adapter.list_user_cards(access_token=access_token)
                # normalise to common shape
                normalised = [{
                    "id": c.get("id") or c.get("card_id"),
                    "brand": c.get("brand") or c.get("network"),
                    "last4": c.get("last4") or c.get("last_four"),
                    "display_name": c.get("name") or c.get("display_name"),
                    "is_default": False,
                } for c in (raw_cards or [])]
                cards = await _upsert_user_cards(db, body.user_id, "astra", normalised)
            except Exception as e:
                logger.warning(f"[astra] card sync after consent failed: {e}")
                cards = []
            return {"ok": True, "cards": cards, "scope": token_resp.get("scope")}

        raise HTTPException(503, f"Active payout provider '{adapter.slug}' not supported")

    @api_router.get("/payout/cards")
    async def list_cards(user_id: str, session_id: str, refresh: bool = False):
        await _require_session(db, user_id, session_id)
        adapter = await get_payout_adapter(db)
        if refresh:
            if isinstance(adapter, StripeConnectPayoutAdapter):
                mapping = await db.connect_user_accounts.find_one(
                    {"user_id": user_id, "gateway_slug": "stripe_connect"}, {"_id": 0}
                )
                if mapping:
                    try:
                        ext_cards = await adapter.list_external_cards(mapping["account_id"])
                        await _upsert_user_cards(db, user_id, "stripe_connect", ext_cards)
                    except Exception as e:
                        logger.warning(f"[stripe-connect] refresh cards failed: {e}")
            elif isinstance(adapter, AstraPayoutAdapter):
                tok = await _load_astra_access_token(db, user_id)
                if tok:
                    try:
                        raw = await adapter.list_user_cards(access_token=tok)
                        await _upsert_user_cards(db, user_id, "astra", [{
                            "id": c.get("id") or c.get("card_id"),
                            "brand": c.get("brand") or c.get("network"),
                            "last4": c.get("last4") or c.get("last_four"),
                            "is_default": False,
                        } for c in raw])
                    except Exception as e:
                        logger.warning(f"[astra] refresh cards failed: {e}")
        rows = await db.payout_user_cards.find(
            {"user_id": user_id, "gateway_slug": adapter.slug, "is_active": True}, {"_id": 0},
        ).sort("created_at", -1).to_list(length=20)
        return {"items": rows, "gateway_slug": adapter.slug}

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

        adapter = await get_payout_adapter(db)
        card = await db.payout_user_cards.find_one(
            {"id": body.card_id, "user_id": body.user_id, "gateway_slug": adapter.slug, "is_active": True},
            {"_id": 0},
        )
        if not card:
            raise HTTPException(412, "Card not found or no longer active. Re-link your payout account.")

        # Build the provider-specific card_token combo
        if isinstance(adapter, StripeConnectPayoutAdapter):
            mapping = await db.connect_user_accounts.find_one(
                {"user_id": body.user_id, "gateway_slug": "stripe_connect"}, {"_id": 0}
            )
            if not mapping or not mapping.get("payouts_enabled"):
                raise HTTPException(412, "Stripe Connect onboarding incomplete. Finish onboarding before cashing out.")
            card_token = f"{mapping['account_id']}|{body.card_id}"
        elif isinstance(adapter, AstraPayoutAdapter):
            access_token = await _load_astra_access_token(db, body.user_id)
            if not access_token:
                raise HTTPException(412, "Astra session expired. Please reconnect your Astra account.")
            card_token = f"{access_token}|{body.card_id}"
        else:
            raise HTTPException(503, f"Active payout provider '{adapter.slug}' not supported")

        txn_id = make_txn_id("payout")
        try:
            result = await adapter.push_to_card(
                amount_cents=requested_cents,
                currency="usd",
                card_token=card_token,
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
            logger.exception(f"[{adapter.slug}] push_to_card failed: {e}")
            raise HTTPException(502, f"Payout gateway error: {e}")

        payout_doc = {
            "id": txn_id, "txn_id": txn_id,
            "user_id": body.user_id, "group_id": body.group_id,
            "gateway_slug": adapter.slug,
            "provider_payout_id": result.provider_payout_id,
            "amount_cents": requested_cents, "currency": "usd",
            "status": result.status, "fee_cents": int(result.fee_cents or 0),
            "card_id": body.card_id, "card_brand": card.get("brand"), "card_last4": card.get("last4"),
            "ledger_posted": False,
            "created_at": now_iso(), "updated_at": now_iso(),
        }
        await db.payouts.insert_one(payout_doc.copy())

        try:
            await record_payout_event(
                db, txn_id=txn_id, bill_id=body.group_id, user_id=body.user_id,
                amount_cents=requested_cents, currency="usd",
                reference={
                    "provider_payout_id": result.provider_payout_id,
                    "gateway_slug": adapter.slug,
                    "card_brand": card.get("brand"), "card_last4": card.get("last4"),
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
            "txn_id": txn_id, "status": result.status,
            "amount": from_cents(requested_cents),
            "provider_payout_id": result.provider_payout_id,
            "card_brand": card.get("brand"), "card_last4": card.get("last4"),
        }

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
        adapter = await get_payout_adapter(db)
        gateway_slug = adapter.slug

        # Provider-linked status
        linked = False
        payouts_enabled = False
        default_card = None
        if isinstance(adapter, StripeConnectPayoutAdapter):
            mapping = await db.connect_user_accounts.find_one(
                {"user_id": user_id, "gateway_slug": "stripe_connect"}, {"_id": 0}
            )
            linked = bool(mapping)
            payouts_enabled = bool(mapping and mapping.get("payouts_enabled"))
        elif isinstance(adapter, AstraPayoutAdapter):
            tok = await db.astra_user_tokens.find_one(
                {"user_id": user_id, "gateway_slug": "astra"}, {"_id": 0}
            )
            linked = bool(tok)
            payouts_enabled = linked  # Astra doesn't have a "payouts_enabled" notion
        if linked:
            default_card = await db.payout_user_cards.find_one(
                {"user_id": user_id, "gateway_slug": gateway_slug, "is_active": True, "is_default": True},
                {"_id": 0},
            )
        return {
            "eligible": eligible,
            "reasons": reasons,
            "available_cents": available,
            "available_usd": from_cents(available),
            "linked": linked,
            "payouts_enabled": payouts_enabled,
            "default_card": default_card,
            "gateway_slug": gateway_slug,
        }

    @api_router.post("/webhook/astra")
    async def astra_webhook(request: Request):
        body_bytes = await request.body()
        sig = request.headers.get("Astra-Signature") or request.headers.get("X-Signature")
        adapter = await get_payout_adapter(db)
        if not isinstance(adapter, AstraPayoutAdapter):
            return {"ok": True, "ignored": "astra not active"}
        try:
            evt = await adapter.verify_webhook(body_bytes, sig)
        except Exception as e:
            logger.exception(f"[astra-webhook] verify failed: {e}")
            raise HTTPException(400, f"Webhook error: {e}")
        return await _apply_payout_webhook(db, evt)

    @api_router.post("/webhook/stripe-connect")
    async def stripe_connect_webhook(request: Request):
        body_bytes = await request.body()
        sig = request.headers.get("Stripe-Signature")
        adapter = await get_payout_adapter(db)
        if not isinstance(adapter, StripeConnectPayoutAdapter):
            return {"ok": True, "ignored": "stripe_connect not active"}
        try:
            evt = await adapter.verify_webhook(body_bytes, sig)
        except Exception as e:
            logger.exception(f"[stripe-connect-webhook] verify failed: {e}")
            raise HTTPException(400, f"Webhook error: {e}")
        return await _apply_payout_webhook(db, evt)


async def _apply_payout_webhook(db, evt) -> dict:
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
            {"$set": {"status": status, "updated_at": now_iso(), "last_webhook_at": now_iso()}},
        )
    return {"ok": True, "payout_id": payout["id"], "new_status": status or payout.get("status")}
