"""Group CRUD + items + assignments + meta-update routes (Batch B refactor)."""
import logging
import os
from fastapi import APIRouter, HTTPException

from core import (
    CreateGroupIn, JoinGroupIn, RemoveMemberIn, UpdateItemsIn, AppendItemsIn,
    UpdateGroupMetaIn, ItemPatchIn, AssignIn, SetSplitModeIn,
    new_id, new_short_code, now_iso,
    _apply_group_discount, _load_group_enriched, _recompute_group,
)

logger = logging.getLogger(__name__)


def attach_groups_routes(router: APIRouter, db):

    @router.post("/groups")
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
            "status": "open",
            "funding_mode": None,
            "virtual_card": None,
            "items": items,
            "assignments": [],
            "members": [{"user_id": body.lead_id, "role": "lead", "joined_at": now_iso()}],
            "contributions": [],
            "repayments": [],
            "lead_paid_at": None,
            "discount": discount_doc,
            "created_at": now_iso(),
        }
        await db.groups.insert_one(group.copy())
        return await _load_group_enriched(db, gid)

    @router.get("/groups/{group_id}")
    async def get_group(group_id: str):
        return await _load_group_enriched(db, group_id)

    @router.get("/groups/by-code/{code}")
    async def get_group_by_code(code: str):
        group = await db.groups.find_one({"code": code}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        return await _load_group_enriched(db, group["id"])

    @router.post("/groups/{group_id}/join")
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
            # Normalise the join-source for backend analytics. Captured per
            # member-doc so the admin can later report on how members were
            # acquired (code vs QR vs link vs invite vs manual).
            joined_via = (body.joined_via or "unknown").lower().strip()
            if joined_via not in {"code", "qr", "link", "invite", "manual", "unknown"}:
                joined_via = "unknown"
            members.append({
                "user_id": body.user_id,
                "role": "member",
                "joined_at": now_iso(),
                "joined_via": joined_via,
            })
            await db.groups.update_one({"id": group_id}, {"$set": {"members": members}})
        return await _load_group_enriched(db, group_id)

    @router.post("/groups/{group_id}/split-mode")
    async def set_split_mode(group_id: str, body: SetSplitModeIn):
        """Lead changes the bill's split mode mid-flight.

        Allowed modes: "fast" (equal split across members) and "itemized"
        (per-item claims). When the mode changes:
          • All item claims may be released if switching to "fast" (the
            core recompute treats fast bills as having no claims).
          • Per-user shares are recomputed immediately.

        The frontend warns the lead before calling this — but the backend
        also enforces:
          • Only the lead can change the mode.
          • Mode cannot change once contributions have already started
            (would invert what some members already paid).
          • Must be one of the two valid modes.
        """
        mode = (body.split_mode or "").strip().lower()
        if mode not in {"fast", "itemized"}:
            raise HTTPException(400, "split_mode must be 'fast' or 'itemized'")

        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        if group.get("is_blocked"):
            raise HTTPException(403, "This group has been blocked by an administrator.")
        if group.get("lead_id") != body.user_id:
            raise HTTPException(403, "Only the lead can change the split mode")
        if group.get("status") != "open":
            raise HTTPException(400, "Split mode is locked — bill is no longer open.")
        # Block once anyone has contributed/repaid — switching would invert
        # what they already paid for.
        contributed = float((group.get("funding") or {}).get("total_contributed") or 0)
        repaid = float((group.get("funding") or {}).get("total_repaid") or 0)
        if contributed > 0.01 or repaid > 0.01:
            raise HTTPException(
                400,
                "Split mode cannot change after contributions have started. "
                "Refund all contributions first if you need to switch.",
            )

        if group.get("split_mode") == mode:
            return await _load_group_enriched(db, group_id)

        await db.groups.update_one(
            {"id": group_id},
            {"$set": {"split_mode": mode}},
        )
        return await _load_group_enriched(db, group_id)

    @router.post("/groups/{group_id}/remove-member")
    async def remove_member(group_id: str, body: RemoveMemberIn):
        """Lead removes a non-contributing member from the bill.

        Strict rules (per product spec):
          • Only the lead can remove.
          • Bill must still be `open` (no removal once contributions are complete).
          • Target cannot be the lead.
          • Target must have ZERO contribution AND ZERO repayment.
          • Target's item assignments are released back to unclaimed.
          • All members get an in-bill notification of the removal.
        """
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        if group.get("is_blocked"):
            raise HTTPException(403, "This group has been blocked by an administrator.")
        if group.get("lead_id") != body.user_id:
            raise HTTPException(403, "Only the lead can remove members")
        if group.get("status") != "open":
            raise HTTPException(400, "Members can no longer be removed — contributions are complete.")
        if body.target_id == group.get("lead_id"):
            raise HTTPException(400, "The lead cannot be removed from their own bill")

        members = group.get("members", []) or []
        target = next((m for m in members if m.get("user_id") == body.target_id), None)
        if not target:
            raise HTTPException(404, "Member is not part of this group")

        # Block if the target has put any money in (contribution or repayment).
        contributions_total = sum(
            float(c.get("amount") or 0)
            for c in (group.get("contributions") or [])
            if c.get("user_id") == body.target_id
        )
        repayments_total = sum(
            float(r.get("amount") or 0)
            for r in (group.get("repayments") or [])
            if r.get("user_id") == body.target_id
        )
        if contributions_total > 0.01 or repayments_total > 0.01:
            raise HTTPException(
                400,
                "This member has already contributed to the bill. Refund their contribution first before removing them.",
            )

        # Fetch the target's display name for the notification copy. Falls
        # back to "a member" if the users collection lookup misses.
        target_user = await db.users.find_one({"id": body.target_id}, {"_id": 0, "name": 1})
        target_name = (target_user or {}).get("name") or "a member"
        lead_user = await db.users.find_one({"id": body.user_id}, {"_id": 0, "name": 1})
        lead_name = (lead_user or {}).get("name") or "the lead"

        # Drop them from members, release their item claims, leave any
        # historical fields (contributions/repayments arrays) untouched
        # because the guards above already confirmed they're empty.
        new_members = [m for m in members if m.get("user_id") != body.target_id]
        new_assignments = [
            a for a in (group.get("assignments") or [])
            if a.get("user_id") != body.target_id
        ]

        # Build a per-user notification so EVERYONE on the bill sees the
        # removal in their notification panel (including the removed user
        # so they understand why they lost access).
        notif_msg = f"{lead_name} removed {target_name} from the bill."
        new_notifications = list(group.get("notifications") or [])
        for m in members:  # iterate over ORIGINAL members so target gets notified too
            new_notifications.append({
                "id": f"notif_{group_id[-6:]}_{m['user_id'][-4:]}_{int(__import__('time').time() * 1000)}",
                "user_id": m["user_id"],
                "message": notif_msg,
                "created_at": now_iso(),
                "kind": "member_removed",
            })

        await db.groups.update_one(
            {"id": group_id},
            {"$set": {
                "members": new_members,
                "assignments": new_assignments,
                "notifications": new_notifications,
            }},
        )
        return await _load_group_enriched(db, group_id)

    @router.patch("/groups/{group_id}")
    async def update_group_meta(group_id: str, body: UpdateGroupMetaIn):
        """Lead-only: update bill title, tax, or tip after creation."""
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        if group["lead_id"] != body.user_id:
            raise HTTPException(403, "Only the lead can edit the bill")

        update_fields = {}
        enriched_now = await _recompute_group(group)
        derived = enriched_now["derived_status"]

        if body.title is not None:
            if derived in ("contributed", "repaying", "settled") or group.get("status") != "open":
                raise HTTPException(400, "Title is locked once all contributions are complete.")
            title = body.title.strip()
            if not title:
                raise HTTPException(400, "Title cannot be empty")
            update_fields["title"] = title

        if body.tax is not None or body.tip is not None:
            if group.get("status") != "open":
                raise HTTPException(400, "Tax/tip can no longer be edited — bill has been settled.")
            new_tax = float(body.tax) if body.tax is not None else float(group.get("tax", 0))
            new_tip = float(body.tip) if body.tip is not None else float(group.get("tip", 0))
            if new_tax < 0 or new_tip < 0:
                raise HTTPException(400, "Tax/tip must be non-negative")
            update_fields["tax"] = new_tax
            update_fields["tip"] = new_tip

            subtotal = sum(it["price"] * it.get("quantity", 1) for it in group.get("items", []))
            if subtotal <= 0 and group.get("split_mode") == "fast":
                old_tax = float(group.get("tax", 0))
                old_tip = float(group.get("tip", 0))
                current_total = float(group.get("total_amount", 0))
                new_total = current_total - old_tax - old_tip + new_tax + new_tip
                update_fields["total_amount"] = round(max(0.0, new_total), 2)
            else:
                update_fields["total_amount"] = round(subtotal + new_tax + new_tip, 2)

        if not update_fields:
            return await _load_group_enriched(db, group_id)
        await db.groups.update_one({"id": group_id}, {"$set": update_fields})
        return await _load_group_enriched(db, group_id)

    @router.put("/groups/{group_id}/items")
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
        return await _load_group_enriched(db, group_id)

    @router.post("/groups/{group_id}/items/append")
    async def append_items(group_id: str, body: AppendItemsIn):
        """Lead-only: add new items to an existing group."""
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        if group["lead_id"] != body.user_id:
            raise HTTPException(403, "Only lead can add items")
        raw_status = group.get("status") or "open"
        vc = group.get("virtual_card") or {}
        card_charged = float(vc.get("spent") or 0) > 0.005 or vc.get("status") == "inactive"
        if raw_status == "closed" or card_charged:
            raise HTTPException(400, "Virtual card has been charged — items can no longer be added.")
        new_items = [
            {"id": new_id("it_"), "name": it.name, "price": it.price, "quantity": it.quantity}
            for it in body.items
        ]
        items = (group.get("items") or []) + new_items
        extra = sum(it["price"] * it["quantity"] for it in new_items)
        new_total = round(float(group.get("total_amount") or 0) + extra, 2)
        update_doc = {"items": items, "total_amount": new_total}
        if raw_status == "paid":
            update_doc["status"] = "open"
            update_doc["funding_mode"] = group.get("funding_mode") or "group"
        await db.groups.update_one({"id": group_id}, {"$set": update_doc})
        if vc.get("stripe_card_id") and vc.get("status") == "active":
            try:
                new_cap_cents = int(round(new_total * 100))
                import stripe as _stripe_sdk
                _stripe_sdk.api_key = os.environ.get("STRIPE_API_KEY")
                _stripe_sdk.issuing.Card.modify(
                    vc["stripe_card_id"],
                    spending_controls={
                        "spending_limits": [{"amount": max(new_cap_cents, 100), "interval": "all_time"}],
                    },
                )
                await db.groups.update_one(
                    {"id": group_id},
                    {"$set": {"virtual_card.spend_cap": round(new_total, 2)}},
                )
            except Exception as e:
                logger.warning(f"[items-append] update card spend cap failed: {e}")
        return await _load_group_enriched(db, group_id)

    @router.delete("/groups/{group_id}/items/{item_id}")
    async def delete_item(group_id: str, item_id: str, user_id: str):
        """Lead-only: remove an item from the bill."""
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
        return await _load_group_enriched(db, group_id)

    @router.patch("/groups/{group_id}/items/{item_id}")
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
        return await _load_group_enriched(db, group_id)

    @router.post("/groups/{group_id}/assign")
    async def assign_item(group_id: str, body: AssignIn):
        group = await db.groups.find_one({"id": group_id}, {"_id": 0})
        if not group:
            raise HTTPException(404, "Group not found")
        item = next((i for i in group.get("items", []) if i["id"] == body.item_id), None)
        if not item:
            raise HTTPException(404, "Item not found")

        assignments = group.get("assignments", [])
        assignments = [a for a in assignments if not (a["user_id"] == body.user_id and a["item_id"] == body.item_id)]

        claimed_by_others = sum(a["quantity"] for a in assignments if a["item_id"] == body.item_id)
        if body.quantity < 0:
            raise HTTPException(400, "Quantity must be >= 0")
        if claimed_by_others + body.quantity > item["quantity"]:
            raise HTTPException(400, "Quantity exceeds available")

        if body.quantity > 0:
            assignments.append({"user_id": body.user_id, "item_id": body.item_id, "quantity": body.quantity})

        await db.groups.update_one({"id": group_id}, {"$set": {"assignments": assignments}})
        return await _load_group_enriched(db, group_id)
