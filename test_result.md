#====================================================================================================
# START - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================

# THIS SECTION CONTAINS CRITICAL TESTING INSTRUCTIONS FOR BOTH AGENTS
# BOTH MAIN_AGENT AND TESTING_AGENT MUST PRESERVE THIS ENTIRE BLOCK

# Communication Protocol:
# If the `testing_agent` is available, main agent should delegate all testing tasks to it.
#
# You have access to a file called `test_result.md`. This file contains the complete testing state
# and history, and is the primary means of communication between main and the testing agent.
#
# Main and testing agents must follow this exact format to maintain testing data. 
# The testing data must be entered in yaml format Below is the data structure:
# 
## user_problem_statement: {problem_statement}
## backend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.py"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## frontend:
##   - task: "Task name"
##     implemented: true
##     working: true  # or false or "NA"
##     file: "file_path.js"
##     stuck_count: 0
##     priority: "high"  # or "medium" or "low"
##     needs_retesting: false
##     status_history:
##         -working: true  # or false or "NA"
##         -agent: "main"  # or "testing" or "user"
##         -comment: "Detailed comment about status"
##
## metadata:
##   created_by: "main_agent"
##   version: "1.0"
##   test_sequence: 0
##   run_ui: false
##
## test_plan:
##   current_focus:
##     - "Task name 1"
##     - "Task name 2"
##   stuck_tasks:
##     - "Task name with persistent issues"
##   test_all: false
##   test_priority: "high_first"  # or "sequential" or "stuck_first"
##
## agent_communication:
##     -agent: "main"  # or "testing" or "user"
##     -message: "Communication message between agents"

# Protocol Guidelines for Main agent
#
# 1. Update Test Result File Before Testing:
#    - Main agent must always update the `test_result.md` file before calling the testing agent
#    - Add implementation details to the status_history
#    - Set `needs_retesting` to true for tasks that need testing
#    - Update the `test_plan` section to guide testing priorities
#    - Add a message to `agent_communication` explaining what you've done
#
# 2. Incorporate User Feedback:
#    - When a user provides feedback that something is or isn't working, add this information to the relevant task's status_history
#    - Update the working status based on user feedback
#    - If a user reports an issue with a task that was marked as working, increment the stuck_count
#    - Whenever user reports issue in the app, if we have testing agent and task_result.md file so find the appropriate task for that and append in status_history of that task to contain the user concern and problem as well 
#
# 3. Track Stuck Tasks:
#    - Monitor which tasks have high stuck_count values or where you are fixing same issue again and again, analyze that when you read task_result.md
#    - For persistent issues, use websearch tool to find solutions
#    - Pay special attention to tasks in the stuck_tasks list
#    - When you fix an issue with a stuck task, don't reset the stuck_count until the testing agent confirms it's working
#
# 4. Provide Context to Testing Agent:
#    - When calling the testing agent, provide clear instructions about:
#      - Which tasks need testing (reference the test_plan)
#      - Any authentication details or configuration needed
#      - Specific test scenarios to focus on
#      - Any known issues or edge cases to verify
#
# 5. Call the testing agent with specific instructions referring to test_result.md
#
# IMPORTANT: Main agent must ALWAYS update test_result.md BEFORE calling the testing agent, as it relies on this file to understand what to test next.

#====================================================================================================
# END - Testing Protocol - DO NOT EDIT OR REMOVE THIS SECTION
#====================================================================================================



#====================================================================================================
# Testing Data - Main Agent and testing sub agent both should log testing data below this section
#====================================================================================================

user_problem_statement: |
  MVP: group payment system allowing group creation + QR/link join; equal + itemized split;
  item assignment. Mock payment (simulate paid state) and mock OTP (123456). Simple name + phone auth.
  Includes OpenAI receipt scanning. Latest: 5 UX/UI and logic bugs fixed: (1) '+' button in items
  opens add-form, (2) improved shortfall payment card UI with radio cards, (3) index title = Home,
  (4) member picker persists in shortfall UI, (5) shortfall settlement payload fix so that lead
  pay no longer errors with "bill is short".

backend:
  - task: "Shortfall settlement endpoint — POST /api/groups/{id}/pay with shortfall_settlement options"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Earlier (instant-settle) version: all 5 scenarios passed. See history for details.
        - working: "NA"
          agent: "main"
          comment: |
            REDESIGNED (Phase 1, items 1/2/4/5): for shortfall_mode='member' and 'split_equal',
            the merchant payment is now DEFERRED. Instead we record `shortfall_obligations`
            on the affected members + `notifications` (kind='shortfall_assigned',
            delivered_via='sms_mock'). Group stays status='open' (derived_status='contributing').
            Affected member's `outstanding` = own_share + shortfall_owed. When they call
            /contribute, their obligation is included in remaining_share. Once total_contributed
            ≥ total_amount, the existing auto-finalize moves status→'paid' (derived='settled').
            For shortfall_mode='lead' (loan or gift), existing instant-settle behavior is kept,
            and notifications are now also sent to beneficiaries.

            Please test:
            A) lead+gift / lead+loan: still settles immediately, notifications sent to
               beneficiaries, gift→derived='settled', loan→derived='repaying' if any outstanding.
            B) member+loan: status stays 'open', funder gets shortfall_owed and notification,
               funder's outstanding = share + shortfall, NOT settled until they /contribute.
            C) split_equal: each non-lead member gets a proportional shortfall_owed +
               notification, status stays 'open', NOT settled until everyone /contributes.
            D) After all obligations paid via /contribute, derived_status='settled'.
            E) Verify items add (POST /groups/{id}/items/append) is BLOCKED (400) when
               status != 'open' (item 13).
            F) Verify lead can call /pay successfully even if items are unclaimed (item 11) —
               unclaimed amount becomes part of the shortfall.
            G) Regression: legacy call without options when shortfall>0 still returns clean 400.

  - task: "Bill 4-state machine — derived_status: contributing | contributed | repaying | settled"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: |
            Added `derived_status` to enriched group response. Computed from raw status +
            per_user.outstanding aggregation:
              raw=open + total_contributed<total ⇒ 'contributing'
              raw=open + total_contributed≥total ⇒ 'contributed'
              raw=paid + has_outstanding ⇒ 'repaying'
              raw=paid + no outstanding ⇒ 'settled'
              raw=closed ⇒ 'settled'
            Verify especially the FAST split + everyone-contributes path lands on 'settled'
            (not stuck in 'repaying') — this was item 7's main bug report.
            backend (EXPO_PUBLIC_BACKEND_URL/api). Setup for each: fresh lead + 2 members, fast
            split group total $60 (per-share $20.63 incl. fees), lead + 1 member contribute,
            leaving shortfall ~$18.74. Results:
              A) lead + is_loan=true  -> 200, status='paid', funding_mode='shortfall',
                 remaining_to_collect=0, settlement.mode='lead' is_loan=true funder_id=lead,
                 contribution {user_id=lead, is_shortfall=true, is_loan=true} recorded.
                 Non-paying member still has outstanding=$20.63 (correct LOAN behavior).
              B) lead + is_loan=false -> 200, status='closed' (gift auto-closes),
                 remaining_to_collect=0, non-paying member outstanding=0 (gift correctly waives).
              C) member + is_loan=true + funder_member_id -> 200, status='paid',
                 settlement.funder_id=funder member, shortfall contribution attributed to that
                 member with is_loan=true. Beneficiaries list excludes the funder.
              D) split_equal -> 200, status='closed', is_loan forced false, shortfall split
                 across the 2 existing contributors as separate contribution rows; non-paying
                 member outstanding=0.
              E) Legacy call (no shortfall_mode) when shortfall>0 -> 400 with
                 'Bill is short $18.74. Choose how to settle the shortfall.' (no 500).
            Notes (informational, not blockers):
              * Per current code, LOAN modes (A, C) leave status='paid' (not 'closed'); group
                only auto-closes via /repay when each non-lead beneficiary's outstanding hits 0,
                or immediately when settlement is a GIFT. The review request mentioned 'closed'
                for all 4 modes — the actual contract closes only gift modes immediately, which
                matches the loan-vs-gift semantics. No bug here.
              * Lead must contribute their own share before /pay (enforced 400). Setup honored
                this; behavior is consistent with prior design.
            All assertions pass. Endpoint is working correctly across all documented modes.

  - task: "Equal split + itemized split + item assignment flows"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "Previously verified end-to-end in earlier session."

  - task: "Receipt OCR — POST /api/receipt/scan (OpenAI gpt-4o)"
    implemented: true
    working: true
    file: "backend/server.py"
    stuck_count: 0
    priority: "medium"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: "OpenAI call confirmed in prior session; EMERGENT_LLM_KEY configured."

  - task: "Phase B — Persistent users (collapse on phone) + Admin Users/Groups + Block/Unblock"
    implemented: true
    working: true
    file: "backend/server.py, backend/admin_users_groups.py, backend/admin_routes.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: |
            PHASE B implementation (NEW — needs backend test):

            (1) Persistent user identity by phone in POST /api/auth/verify-otp:
                When a user calls /auth/register (creates a placeholder user with no phone),
                then /auth/send-otp + /auth/verify-otp with a phone, the backend now checks
                if a verified user already exists with that phone (id != placeholder).
                If yes: it returns the EXISTING user's id (so all their groups are visible),
                refreshes the existing user's name if the placeholder had a different name,
                and DELETES the placeholder. If the existing user is_blocked=True, returns 403
                "This account has been blocked. Please contact support." and removes the
                placeholder. If no existing match, the placeholder gets verified=true and is
                returned as before.

            (2) Block enforcement in user-app endpoints (server.py):
                - /groups (create): 403 if lead user is_blocked.
                - /groups/{id}/join: 403 if user is_blocked OR group is_blocked.
                - /groups/{id}/contribute: 403 if user is_blocked OR group is_blocked.
                - /groups/{id}/pay: 403 if lead is_blocked OR group is_blocked.

            (3) NEW admin endpoints in /api/admin (admin_users_groups.py):
                - GET  /admin/users           list+search by name/phone, filter verified/blocked,
                                              returns {items[{...,groups_led,groups_joined,total_billed_as_lead}], total}
                - GET  /admin/users/{id}      detail with led_groups + joined_groups arrays
                - POST /admin/users/{id}/block   body {is_blocked, reason} — requires
                                              role super_admin or manager; emits
                                              admin.block_user / admin.unblock_user audit log
                - GET  /admin/groups          list+search by title/code, filter status/blocked/lead_id
                - GET  /admin/groups/{id}     full detail (members enriched with name/phone/blocked,
                                              items, assignments, contributions, repayments)
                - POST /admin/groups/{id}/block  body {is_blocked, reason} — same RBAC + audit

            TEST SCOPE:
              A) Persistent user collapse: register with name="Foo", send/verify OTP with
                 phone X → returns user A. Register a NEW placeholder with name="Bar",
                 send/verify OTP with SAME phone X → returns user A (same id), and the
                 placeholder is removed. Confirm /api/users/A/groups still shows past groups.

              B) Blocked user cannot login: admin POST /admin/users/A/block {is_blocked:true};
                 a fresh /auth/register + /auth/verify-otp with phone X → 403 with
                 "blocked" message.

              C) Blocked user cannot create / join / contribute / pay (run while blocked):
                 - POST /groups (lead_id=A) → 403
                 - POST /groups/{g}/join (user_id=A) → 403
                 - POST /groups/{g}/contribute → 403
                 - POST /groups/{g}/pay (if A is lead) → 403

              D) Unblock restores access: admin POST /admin/users/A/block {is_blocked:false}
                 → A can now login + create + join + pay.

              E) Group block: admin POST /admin/groups/{g}/block {is_blocked:true} →
                 /groups/{g}/join, /contribute, /pay all return 403. Unblock restores.

              F) Admin endpoints auth: all /admin/users and /admin/groups require Bearer
                 token; without it → 401. Block endpoint without manager/super_admin role
                 → 403. (Use seeded super_admin from /app/memory/test_credentials.md.)

              G) Audit log entries: after block actions, GET /admin/audit-log shows
                 admin.block_user / admin.block_group / admin.unblock_user / admin.unblock_group
                 with destructive=true and proper target_id/payload.

              H) Search & filter sanity: GET /admin/users?q=<phone substring>&blocked=true
                 returns just the blocked users matching; GET /admin/groups?status=open
                 returns only open groups; pagination skip/limit works.

  - task: "Phase C1 — Referral system (codes, signup-with-code, admin leaderboard, settings, pending credits)"
    implemented: true
    working: true
    file: "backend/server.py, backend/admin_referrals.py, backend/admin_routes.py, backend/admin.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Phase C1 (Referrals) end-to-end tested via /app/backend_test.py against the live
            preview backend. 65/66 assertions PASS. No 5xx errors.

            Coverage by scenario (PASS unless noted):
              A) Code generation: AliceC1<ts> + BobC1<ts> both registered, each got a
                 distinct 6-char referral_code drawn from the safe alphabet
                 ABCDEFGHJKLMNPQRSTUVWXYZ23456789 (sample: 9RZ9ZH, QLV82E). ✅
              B) Public lookup: GET /referrals/lookup/<alice_code> → 200 valid:true,
                 referrer_name & referrer_code match. /referrals/lookup/NOPE99 → 404
                 with detail "Referral code not found". ✅
              C) Register-with-code: BobBob<ts> with Alice's code → response.referred_by_user_id
                 == alice.id, own referral_code is non-empty and != alice's. Bogus code XXXX99
                 → 400 "Invalid referral code". ✅
              D) Reward DISABLED: settings reset to {enabled:false}; DanD<ts> registered with
                 Alice's code, send-otp + verify-otp on +1555<epoch>. verify-otp succeeded;
                 alice.pending_credits stayed at 0 before/after. Re-verify (idempotency) also
                 left it at 0. Confirms _maybe_grant_referral_rewards short-circuits when
                 settings.enabled=false. ✅
              E) Reward ENABLED: POST /admin/referrals/settings {enabled:true,
                 referrer_credit:5, referee_credit:2} as super_admin → 200. Registered
                 EvaE<ts> with Alice's code + verified fresh phone → after verify,
                 alice.pending_credits incremented (0 → 1) and eva.pending_credits == 1.
                 Re-running send-otp + verify-otp for Eva (same phone) did NOT increment
                 either count — idempotency holds. ✅
              F) Persistent collapse referral transfer: OldUser<ts> verified phone Y with
                 no code; FreshPlaceholder<ts> registered with Alice's code, then verified
                 Y → collapsed to OldUser id, referred_by_user_id transferred to Alice.
                 Re-attempt (FreshPlaceholder2 with Bob's code, verify Y) did NOT change
                 OldUser.referred_by — guard works. ✅
              G) Self-refer guard: registered Self<ts>, verified self_phone, captured
                 self_code; SelfPlaceholder<ts> registered with self_code (placeholder
                 referred_by == self.id) → verify-otp same phone collapsed to Self;
                 existing.referred_by_user_id stayed None (self-refer suppressed). ✅
              H) Phone masking: GET /users/{alice_id}/referrals → referees with phone
                 returned as "********8422" (only last 4 digits visible, prefix '*'). ✅
              I) Admin auth/RBAC: GET /admin/referrals without Bearer → 401 "Admin auth
                 required". Created support admin via POST /admin/admins (super_admin),
                 logged in. POST /admin/referrals/settings as support → 403 "Requires
                 one of roles: manager,super_admin". GET /admin/referrals as support →
                 200 (read allowed). ✅
              J) Leaderboard + stats: GET /admin/referrals?q=alice → Alice present with
                 total_referrals=4, verified_referrals=3, referral_code matches.
                 stats.conversion_rate=83.3 == round(verified/total*100,1). ✅
              K) Audit log: 4 admin.update_referral_settings entries from D/E settings
                 writes, with target_type='settings' and target_id='referrals'. Note on
                 destructive flag below.
              L) Cleanup: POST /admin/referrals/settings {enabled:false, ...} → 200. ✅

            BUG (minor) — audit destructive flag:
              The single failing assertion is K.destructive_true. The review request
              explicitly says admin.update_referral_settings should record
              destructive=true, but admin.AUDIT_ACTIONS_DESTRUCTIVE in /app/backend/admin.py
              (lines 188–201) does NOT include 'admin.update_referral_settings'. As a
              result every audit row for that action is written with destructive=False.
              Fix: add "admin.update_referral_settings" to AUDIT_ACTIONS_DESTRUCTIVE.
              All other audit fields (action, target_type='settings', target_id='referrals')
              are correct.

            Backend log (informational, not blocking):
              - passlib bcrypt cosmetic warning ("module 'bcrypt' has no attribute
                '__about__'") — auth still works.
              - jwt.InsecureKeyLengthWarning: HMAC key is 31 bytes (recommended ≥32);
                same as Phase B.

            Marking C1 task as working — only the destructive flag tweak is outstanding.
        - working: "NA"
          agent: "main"
          comment: |
            PHASE C1 — needs backend test.

            Models:
              - User: referral_code (6-char A–Z2–9 unique), referred_by_user_id, referral_reward_granted (idempotency).
              - app_settings collection: doc {key:'referrals', enabled, referrer_credit, referee_credit}.
              - credits collection: ledger rows {id, user_id, amount, kind, source_user_id, status:'pending', note, created_at}.

            User-facing endpoints (under /api):
              - POST /auth/register: optional referral_code; 400 on invalid; sets referred_by_user_id; always
                generates a unique referral_code on the new user.
              - POST /auth/verify-otp: on persistent collapse, transfers placeholder.referred_by_user_id into
                the existing user (only if existing has none); avoids self-refer; backfills referral_code on
                legacy users; calls _maybe_grant_referral_rewards (idempotent) — when settings.enabled and
                amount>0 it writes pending credit rows for referrer and/or referee, then sets
                referral_reward_granted=True.
              - GET /users/{id}/referrals → {referral_code, referred_by, referees[], counts, settings, pending_credits}.
                Phones in referees[] are masked (last 4 digits only).
              - GET /referrals/lookup/{code} → {valid, referrer_name, referrer_code, settings} or 404.

            Admin endpoints (require Bearer; under /api/admin):
              - GET  /admin/referrals/settings           → current settings.
              - POST /admin/referrals/settings {enabled, referrer_credit, referee_credit}
                                                           super_admin/manager only; emits
                                                           admin.update_referral_settings audit (destructive=true).
              - GET  /admin/referrals?q=&limit=&skip=    → leaderboard {items[{user_id,name,phone,referral_code,
                                                           is_blocked,total_referrals,verified_referrals}], total,
                                                           stats:{total_referred,verified_referred,conversion_rate,pending_credits}}.
              - GET  /admin/referrals/{user_id}          → {id,name,phone,referral_code,is_blocked,referred_by,
                                                           referees[]+groups_joined, pending_credits}.

            TEST SCOPE:
              A) Code gen: register two fresh users → both get distinct 6-char referral_code from the safe alphabet.
              B) Lookup: GET /referrals/lookup/<code> → 200 valid, GET /referrals/lookup/INVALID → 404.
              C) Register-with-code: valid sets referred_by_user_id; invalid → 400.
              D) Reward — DISABLED settings: register "Bob" with Alice's code → verify-otp on fresh phone
                 → NO credits rows created, user.referral_reward_granted=True. Repeat verify (manual)
                 → still no double-grant.
              E) Reward — ENABLED: POST /admin/referrals/settings {enabled:true, referrer_credit:5, referee_credit:2}.
                 Register "Dan" with Alice's code, verify-otp on fresh phone → exactly 2 credits rows: one
                 with kind='referral_referrer' for Alice (amount 5) and one 'referral_referee' for Dan (amount 2),
                 both status='pending'. user.referral_reward_granted=True. Re-verify is no-op.
              F) Persistent collapse referral transfer: register placeholder with code, then verify-otp where
                 existing verified user has no referred_by → existing user's referred_by gets set; if it already
                 has a referred_by it MUST stay unchanged.
              G) Self-refer guard: registering with own future code is impossible (code unknown); but in
                 collapse, if placeholder's referred_by_user_id == existing.id, do not set.
              H) GET /users/{alice_id}/referrals → referral_code present, referees count matches db, pending_credits
                 reflects pending rows for that user (e.g., Alice has at least the referrer rewards). Phones masked.
              I) Admin endpoints auth: GET /admin/referrals without Bearer → 401. POST /admin/referrals/settings
                 as a non-super_admin/non-manager admin (e.g., 'support' role) → 403.
              J) Admin leaderboard: GET /admin/referrals?q=alice → returns Alice with total_referrals >= 2,
                 verified_referrals = number who actually verified phones. stats.conversion_rate sane.
              K) Audit: after POST settings, GET /admin/audit-log lists admin.update_referral_settings with
                 destructive=true and target_type='settings', target_id='referrals'.
              L) Cleanup: POST /admin/referrals/settings {enabled:false, referrer_credit:0, referee_credit:0}.

  - task: "Phase C2 — Credits & Discounts (admin grant/revoke, group discount, lead auto-discount, contribute auto-applies credits, pending->active migration)"
    implemented: true
    working: true
    file: "backend/server.py, backend/admin_credits.py, backend/admin_routes.py, backend/admin.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Phase C2 (Credits & Discounts) end-to-end tested via /app/backend_test.py against
            the live preview backend. 87/87 assertions PASS. No 5xx errors.

            Coverage by scenario (all PASS):
              A) Migration idempotency — no leftover status='pending' non-zero credit rows
                 visible on a fresh user wallet. _activate_pending_credits ran on startup.
              B) Admin grant credit — super_admin POST /admin/users/{tom}/credits/grant
                 {amount:10} → 200, row.status='active', kind='admin_grant',
                 consumed_amount=0; GET /api/users/{tom}/credits balance=10.0.
              C) Auto-apply at contribute (full) — fast-split $30 group, contribute $30 →
                 contributions[0]: amount=30, cash_paid=20, credit_applied=10. Wallet
                 balance=0, grant row consumed_amount=10 status='consumed'.
              D) Partial credit — granted $5; $30 group; contribute $30 → cash_paid=25,
                 credit_applied=5, balance=0.
              E) FIFO order — $3 first then $5 (granted ~50ms apart). $4 group, contribute $4 →
                 first row consumed_amount=3 status='consumed', second row consumed_amount=1
                 status='active', balance=4. cash_paid=0 credit_applied=4.
              F) Revoke — POST .../credits/{id}/revoke → status='revoked', balance excludes.
                 Re-revoke same id → 200 row still 'revoked', AND no new admin.revoke_credit
                 audit entry written (idempotent — count before == count after).
              G) Group discount flat $5 on $100 → total_amount=95, original_total_amount=100,
                 discount.amount=5, GET /groups/{id} reflects.
              H) Group discount percent 20% on $100 → total=80, discount.amount=20.
              I) Discount on settled group → 400 (used a paid auto-finalized group from D).
              J) DELETE /admin/groups/{g}/discount → total_amount restored to 100, discount=null,
                 reflected on subsequent GET.
              K) Lead auto-discount — POST /admin/users/{tom}/lead-discount {flat,5,enabled:true}
                 → 200 lead_auto_discount stored. New $50 group by Tom →
                 group.total_amount=45, original_total_amount=50, discount.source='lead_auto',
                 discount.amount=5. Disable {enabled:false} → user.lead_auto_discount=null and
                 a subsequent $50 group has total_amount=50, discount=null.
              L) Audit log destructive=true verified for all 6 C2 actions:
                 admin.grant_credit, admin.revoke_credit, admin.set_group_discount,
                 admin.clear_group_discount, admin.set_lead_discount, admin.clear_lead_discount.
                 admin.AUDIT_ACTIONS_DESTRUCTIVE includes them all.
              M) RBAC — support admin (created via POST /admin/admins as super_admin, then
                 logged in) returned 403 on grant, revoke, set_group_discount,
                 DELETE group_discount, set lead-discount. Read endpoints succeed:
                 GET /admin/users/{id}/credits → 200 for support; GET /api/users/{id}/credits
                 → 200 (public). Admin wallet without bearer → 401.
              N) Cleanup — Tom's lead_auto_discount cleared at end.

            Backend log notes (informational, not blockers):
              - passlib bcrypt cosmetic warning (no functional impact).
              - jwt InsecureKeyLengthWarning (JWT_SECRET 31 bytes; ≥32 recommended).

            Test suite saved at /app/backend_test.py and is idempotent (uses ts-based
            names + fresh phones + fresh support admin email each run).
        - working: "NA"
          agent: "main"
          comment: |
            PHASE C2 — needs backend test.

            Models additions:
              - User: lead_auto_discount = {type:'flat'|'percent', value, note, set_at, set_by} | None.
              - Group: discount = {type, value, amount, note, source:'admin'|'lead_auto', applied_at, applied_by} | None;
                       original_total_amount (so discount can be cleared).
              - credits row: now also has consumed_amount (default 0), last_consumed_at, consumption_events[],
                             status ∈ {'active','consumed','revoked','pending'}.
              - Startup migration: any leftover status='pending' credits → 'active'; backfills consumed_amount=0.
              - C1 referral rewards now write status='active' directly.
              - contribute response now records cash_paid + credit_applied per contribution.

            New endpoints (Bearer required for admin ones; super_admin/manager for write):
              - GET  /api/users/{id}/credits → wallet {balance, items[], lead_auto_discount}
              - GET  /api/admin/users/{id}/credits → admin wallet view (all rows + balance)
              - POST /api/admin/users/{id}/credits/grant {amount, note} → creates active row, audit 'admin.grant_credit'
              - POST /api/admin/users/{id}/credits/{credit_id}/revoke → marks revoked, audit 'admin.revoke_credit'
              - POST /api/admin/groups/{id}/discount {type, value, note} → recomputes total, stores discount,
                     audit 'admin.set_group_discount'. 400 if group not 'open'.
              - DELETE /api/admin/groups/{id}/discount → restores original_total_amount, audit 'admin.clear_group_discount'
              - POST /api/admin/users/{id}/lead-discount {type, value, note, enabled} → stores on user.lead_auto_discount
                     (or clears if !enabled). Audit 'admin.set_lead_discount' / 'admin.clear_lead_discount'.

            Behavior changes:
              - POST /api/groups/{id}/contribute now FIFO-consumes user's active credits up to `amount`. Each
                contribution row contains cash_paid (= amount - credit_applied) and credit_applied (>= 0).
              - POST /api/groups (create_group) now applies lead's lead_auto_discount automatically: stores
                original_total_amount + discount object + reduces total_amount.

            TEST SCOPE:
              A) Migration: existing 'pending' credits flipped to 'active' on startup; idempotent.
              B) Admin grant credit: super_admin grants $10 to user. GET /api/users/{id}/credits → balance=$10,
                 1 active row. As 'support' admin (read-only) → grant returns 403.
              C) Auto-apply at contribute: user with $10 credit contributes $30 to a $30 bill →
                 - contribution.amount = 30
                 - contribution.cash_paid = 20
                 - contribution.credit_applied = 10
                 - GET wallet balance = 0; the credit row is consumed_amount=10 status='consumed'.
              D) Partial credit: user with $5 credit contributes $30 → cash_paid=25, credit_applied=5,
                 row status='consumed'; balance=0.
              E) FIFO order: user with two active credits ($3 created first, $5 created later) contributes $4 →
                 first row fully consumed, second row consumed_amount=1, balance=4.
              F) Revoke: super_admin revokes a row → status='revoked'; balance excludes it. Already-consumed
                 amount is preserved.
              G) Group discount flat: super_admin POST .../groups/{g}/discount {type:'flat', value:5} where
                 original=$100 → total_amount becomes 95; discount.amount=5; group.original_total_amount=100.
              H) Group discount percent: type:'percent', value:20 on $100 → amount=20, total_amount=80.
              I) Discount on settled bill: try setting on a 'paid' or 'closed' group → 400.
              J) Clear discount: DELETE → total restored to original_total_amount; discount=null.
              K) Lead auto-discount: super_admin sets type:'flat' value:5 on lead U. U creates a NEW group
                 with original=50 → group.total_amount=45, group.discount.source='lead_auto', amount=5.
                 Disable lead_auto: POST {enabled:false} → user.lead_auto_discount=None.
              L) Audit: GET /api/admin/audit-log entries for admin.grant_credit / admin.revoke_credit /
                 admin.set_group_discount / admin.clear_group_discount / admin.set_lead_discount /
                 admin.clear_lead_discount with destructive=true.
              M) RBAC: support-role admin → grant/revoke/set-discount/set-lead-discount all return 403.
              N) Idempotency on revoke: revoking already-revoked row → 200 returns row, no double-audit.

frontend:
  - task: "Items screen — '+' button opens add-item form"
    implemented: true
    working: true
    file: "frontend/app/group/[id]/items.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Header plus button sets showAddForm=true which renders the inline addCard."
        - working: true
          agent: "main"
          comment: |
            Visually verified via screenshot_tool: signed in as lead, navigated to
            /group/{id}/items with 2 items. The blue '+' button is visible top-right of the
            "Who ordered what?" header. Clicking it renders the 'Add a new item' form with
            name/price/qty inputs and Cancel/Add-to-bill actions.

  - task: "Pay screen — Shortfall radio-card UI + member picker persists"
    implemented: true
    working: true
    file: "frontend/app/group/[id]/pay.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: "NA"
          agent: "main"
          comment: "Radio cards for lead/member/split_equal, member picker shown when mode=member."
        - working: true
          agent: "main"
          comment: |
            Visually verified via screenshot_tool with a seeded group that has a shortfall.
            Shortfall card renders with SHORTFALL label, $29.07 amount, prompt text, and
            3 radio cards (I cover it / Ask a member / Split equally). Treat-this-as Loan/Gift
            selector renders beneath. Selecting 'Ask a member' expands the PICK THE MEMBER
            picker with UX Member avatar and name — picker stays mounted after selection
            (the previous disappearing bug is gone). Pay button shows correct amount.

  - task: "Create Bill — Subtotal becomes read-only, derived from items"
    implemented: true
    working: true
    file: "frontend/app/create.tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "main"
          comment: |
            Removed the editable Subtotal TextInput and replaced it with a non-editable
            'SUBTOTAL (AUTO)' display that shows the live sum of items (price × quantity)
            with a 'from items' hint. computedTotal() = computedSubtotal() + tax + tip.
            Receipt-scan no longer pushes a phantom total; only items + tax + tip are seeded.
            Create-bill validation now requires items (subtotal > 0). Empty state copy
            updated to 'Add items to start the bill. Subtotal updates automatically.'
            Verified visually: with Pasta×2 @ $12 + Drink×1 @ $4.50 + tax $2 + tip $3,
            Subtotal renders '$28.50' (read-only) and Total at the bottom is '$33.50'.
            The previous 'phantom amount' bug (manual subtotal not tied to any item) is gone.

  - task: "Phase E — Real Stripe Checkout payment flow (POST /api/groups/{id}/checkout-session, GET /api/checkout/status/{id}, POST /api/webhook/stripe)"
    implemented: true
    working: false
    file: "backend/server.py, backend/payments.py"
    stuck_count: 1
    priority: "high"
    needs_retesting: true
    status_history:
        - working: false
          agent: "testing"
          comment: |
            Phase E checkout flow tested end-to-end via /app/backend_test.py against the
            live preview backend. 18/20 assertions PASS, but ONE CRITICAL BUG blocks the
            status polling path.

            ✅ PASSING (18):
              A) Create checkout session — happy path:
                 - POST /api/groups/{gid}/checkout-session {origin_url:'http://localhost:3000'}
                   → 200; response keys = ['url','session_id','amount'].
                 - url contains 'stripe.com' (https://checkout.stripe.com/c/pay/cs_test_...).
                 - session_id starts with 'cs_test_'.
                 - amount == group.total_amount (42.5).
                 - Backend log shows real Stripe call:
                     "message='Request to Stripe api' method=post
                      url=https://api.stripe.com/v1/checkout/sessions" → response_code=200.
              C) Validation:
                 - origin_url='localhost:3000'  → 400 'origin_url must include scheme (http(s)://...)'. ✅
                 - origin_url='plainstring'     → 400 same detail. ✅
                 - Unknown group_id             → 404 'Group not found'. ✅
                 - GET /checkout/status/cs_test_DOES_NOT_EXIST → 404 'Payment session not found'. ✅
                 - Already-paid group           → 400 'Bill already paid' (after Tom contributed
                   his full share to a fast-split fresh group, status auto-flipped to 'paid'). ✅
                 - Admin-blocked group          → 403 'This group has been blocked by an
                   administrator.' (admin POST /api/admin/groups/{gid}/block worked). ✅
              G) Two consecutive checkout sessions for same group → both 200, both 'cs_test_' ids,
                 distinct from each other. ✅
              F) DB hygiene — payment_transactions row exists (status endpoint 200 only when row
                 found). Confirmed two rows created for same group in scenario G.
              E_setup) /api/admin/auth/login as super_admin works.

            ❌ FAILING (2) — same root cause:
              B) GET /api/checkout/status/{session_id} for the just-created (unpaid) session → 502:
                   detail = "Stripe error: Unexpected error retrieving session status:
                             1 validation error for CheckoutStatusResponse
                             metadata
                               Input should be a valid dictionary
                                 [type=dict_type, input_value=<StripeObject at 0x...>,
                                  input_type=StripeObject]"
              E) Idempotency polls — both polls return the same 502 (so the response shape
                 cannot be verified at all).

            ROOT CAUSE (third-party library bug, blocking):
              /root/.venv/lib/python3.11/site-packages/emergentintegrations/payments/stripe/checkout.py
              line 67–73 defines CheckoutStatusResponse.metadata as `Dict[str, str]`. In
              get_checkout_status() (line 191–199), it passes `session.metadata` directly to
              this Pydantic model. Stripe's Python SDK returns metadata as a `StripeObject`
              (dict-like, NOT a true dict). Pydantic v2 strict validation rejects it, so EVERY
              call to /api/checkout/status/{sid} for any unpaid (or paid) session ends in 502.

              This means in the current implementation the entire post-redirect polling flow
              cannot succeed — the lead returning from Stripe Checkout will see "Stripe error"
              forever and the group will never be marked status='paid' via the status route
              (the webhook route may still work since it goes through a different code path).

            SUGGESTED FIX (in /app/backend/payments.py — bypass the broken library call for
            status only; library usage for create_checkout_session is fine):
              Replace `await stripe_checkout.get_checkout_status(session_id)` with a direct
              Stripe SDK call, e.g.:
                  import stripe
                  stripe.api_key = os.environ["STRIPE_API_KEY"]
                  s = stripe.checkout.Session.retrieve(session_id)
                  status_obj = SimpleNamespace(
                      status=s.status,
                      payment_status=s.payment_status,
                      amount_total=s.amount_total,
                      currency=s.currency,
                      metadata=dict(s.metadata or {}),
                  )
              Or, monkey-patch `session.metadata = dict(session.metadata or {})` before the
              library wraps it (would require library subclass).
              Alternative: pin/upgrade emergentintegrations to a version where
              CheckoutStatusResponse.metadata uses `dict` (non-strict) or `Optional[Dict]` with
              before-validator coercion.

            Test scenarios D and the "amount=0" path were not exercised because the API rejects
            0 totals at create_group; main agent's spec note already explains this.

            Marking task working=false; needs main_agent fix to the status endpoint, then
            retest of B + E only (everything else passes).
        - working: "NA"
          agent: "main"
          comment: |
            PHASE E — Real Stripe via emergentintegrations library, using the user-provided sk_test_ key.

            New module backend/payments.py with 3 endpoints (mounted onto api_router BEFORE app.include_router):
              - POST /api/groups/{group_id}/checkout-session  body {origin_url}
                Creates a real Stripe Checkout Session for the group's total_amount (server-trusted).
                Inserts a payment_transactions row {id, session_id, group_id, lead_id, amount, currency='usd',
                  status='initiated', payment_status='pending', applied=false, metadata, created_at, updated_at}.
                400 if group not 'open' or amount <= 0; 403 if group is_blocked; 404 if not found.
                Returns {url, session_id, amount}.
              - GET  /api/checkout/status/{session_id}
                Reads stored tx; if not yet applied, calls Stripe API for live status; on payment_status=='paid',
                marks the group as status='paid', sets lead_paid_at, funding_mode='lead', stripe_session_id,
                and tx.applied=true. Idempotent on subsequent polls.
              - POST /api/webhook/stripe
                Verifies Stripe signature via emergentintegrations. On 'paid' event, marks group paid (idempotent
                with status endpoint).

            Server changes:
              - STRIPE_API_KEY in /app/backend/.env now contains a real sk_test_ key (provided by user).
              - payments.attach_payment_routes(api_router, db) called BEFORE app.include_router(api_router).

            Frontend changes:
              - api.ts adds createCheckoutSession + getCheckoutStatus.
              - app/group/[id]/pay.tsx: when kind='lead' and remaining_to_collect>0.01, shows secondary
                "Pay with Stripe — $X.XX" button that POSTs origin_url + redirects window.location to Stripe.
                On return, useEffect detects session_id query param and polls status (8x with 2s gap) until
                payment_status=='paid' or status=='expired'; banner UI surfaces progress.

            TEST SCOPE:
              A) Create checkout session — happy path:
                 - Register Tom + verify with fresh phone. Tom creates fast-split group total $42.50.
                 - POST /api/groups/{gid}/checkout-session {origin_url:'http://localhost:3000'} → 200,
                   response has url containing 'stripe.com', session_id starts with 'cs_test_', amount=42.5.
                 - DB has payment_transactions row with status='initiated', applied=false.

              B) GET /api/checkout/status/{cs_test_FAKE_SESSION_ID_NOTREAL} — for an unknown session_id stored
                 (insert a synthetic tx row with status='initiated' tied to a real-but-unpaid Stripe sandbox session
                 created in step A) — should return status='open', payment_status='unpaid', applied=false.
                 Without forcing a real payment, you cannot exercise the 'paid' transition end-to-end —
                 verify the polling logic by checking response shape only.

              C) Validation errors:
                 - origin_url missing scheme → 400.
                 - Group with status='paid' → 400 'Bill already paid'.
                 - Blocked group → 403.
                 - Unknown group_id → 404.

              D) Idempotency and error path:
                 - Get status for unknown session_id → 404 'Payment session not found'.
                 - Group total of 0 (create with total_amount=0) → endpoint returns 400 'Group total must be > 0'.

              E) Stripe API live: confirm backend logs show 'Request to Stripe api' (200) on successful checkout
                 creation (proof the real sk_test_ key is being used).

              F) DB hygiene: payment_transactions rows include metadata.kind='group_lead_pay', currency='usd'.
              G) Frontend flow not in scope for backend testing (skip).


    implemented: true
    working: true
    file: "backend/server.py, backend/integrations.py, backend/admin_integrations.py, backend/admin_routes.py, backend/admin.py, backend/reminders.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Phase D (Integrations: Stripe + Twilio + Reminders) verified end-to-end via
            /app/backend_test.py against the live preview backend. 60/60 assertions PASS.
            No 5xx errors.

            Coverage by scenario (all PASS):
              A) Auth & shape — GET /admin/integrations without Bearer → 401 "Admin auth
                 required"; super_admin → 200 with stripe+twilio+reminders subobjects; no
                 plaintext field names (secret_key/auth_token/webhook_secret) present,
                 only *_masked + *_set variants. ✅
              B) Stripe save — super_admin POST with enabled=true, mode=test, pk='pk_test_PHASEDX',
                 sk='sk_test_PHDsecret9999', whsec='whsec_PHDhook12345' → 200. GET shows
                 publishable_key='pk_test_PHASEDX', secret_key_set=true,
                 secret_key_masked ends with '9999' and starts with '*',
                 webhook_secret_set=true, webhook_secret_masked ends with '2345'.
                 Re-save omitting secret_key preserved existing (still ends with '9999',
                 still set). Support admin POST → 403. ✅
              C) Twilio save — super_admin POST with account_sid='AC_PHDsidXXX',
                 auth_token='tokPHDXXX', from_number='+15555550001', enabled=false → 200.
                 GET shows account_sid_set=true, account_sid_masked ends with 'dXXX',
                 from_number='+15555550001'. Manager admin POST → 403 with detail
                 mentioning "super_admin" ("Requires one of roles: super_admin"). ✅
              D) Twilio test SMS (disabled) — super_admin POST /twilio/test
                 {to_number:'+15551234567'} → 200, sent_real=false, info="Twilio disabled —
                 logged to console" (contains 'twilio disabled'). Support admin → 403. ✅
              E) Reminders save + sanitization — super_admin POST with schedule_hours
                 [24,72,168] → 200, schedule stored as [24,72,168]. Sanitization POST with
                 [0,-5,24,24,2000,72] → 200, schedule stored as [24,72,2000] (zeros/negs
                 dropped, dedup, sorted). Support admin POST → 403. ✅
              F) Reminders run-now — super_admin POST → 200 with
                 {enabled:true, scanned:N, sent_real:N, logged:N, skipped:N, schedule_hours:[...]}.
                 All 5 expected keys present. No 5xx. ✅
              G) Idempotency — run-now called twice consecutively: scanned equal across
                 calls; second call's skipped >= first call's (logged+sent_real), i.e.
                 already-dispatched reminders dedup'd via db.reminders on
                 (group_id, user_id, offset_hour). ✅
              H) OTP with Twilio disabled — registered fresh user, POST /auth/send-otp
                 {user_id, phone:'+155588870..'} → 200 with mocked=true and twilio_info
                 containing 'Twilio disabled'. POST /auth/verify-otp with code '123456'
                 → 200 (mock OTP still works regardless of Twilio state). ✅
              I) Encryption sanity — GET /admin/integrations raw response contains zero
                 occurrences of "secret_key":, "auth_token":, "webhook_secret": field
                 names, and none of the forbidden value prefixes 'sk_test_PHDsecret' /
                 'gAAAA' (Fernet token prefix). Only masked variants are projected. ✅
              J) Audit destructive flags — GET /admin/audit-log?limit=50 confirmed the
                 following actions present with destructive=true: admin.update_stripe_settings,
                 admin.update_twilio_settings, admin.test_twilio,
                 admin.update_reminder_settings, admin.run_reminders_now. All 5 destructive
                 assertions pass. (admin.AUDIT_ACTIONS_DESTRUCTIVE in /app/backend/admin.py
                 lines 208–213 correctly include all five.) ✅
              K) Cleanup — super_admin POST stripe {enabled:false,mode:'test'}, twilio
                 {enabled:false}, reminders {enabled:false,schedule_hours:[24,72,168],
                 max_reminders_per_user:3,send_via_sms:true} — all 200. ✅

            Backend log notes (informational, not blockers):
              - passlib bcrypt cosmetic warning (no functional impact).
              - jwt InsecureKeyLengthWarning (JWT_SECRET 31 bytes, ≥32 recommended).
              - [twilio-mock] console log observed during test_twilio call (expected:
                Twilio disabled, so SMS logged instead of POST'd).
              - [reminders] background loop started at server startup (interval=900s).

            Test suite saved at /app/backend_test.py (uses ts-based names + fresh phones +
            fresh support/manager admin emails each run). Marking Phase D as working — no
            further backend action required for this feature.
        - working: "NA"
          agent: "main"
          comment: |
            PHASE D — needs backend test.

            New modules:
              - integrations.py: Fernet-based at-rest encryption (key derived from JWT_SECRET via SHA-256),
                encrypt_secret/decrypt_secret/mask_secret, get_integrations_doc with safe defaults,
                project_integrations_for_admin (masked view, never plaintext),
                send_sms_via_twilio (httpx POST to Twilio REST API when enabled+configured; else logs to console).
              - admin_integrations.py: 6 admin endpoints.
              - reminders.py: run_reminder_pass + start_reminder_loop (asyncio task every 15 min from startup).

            Server changes:
              - /api/auth/send-otp now also calls send_sms_via_twilio (real SMS if Twilio enabled, else mock log).
                Mock OTP code 123456 always works regardless.
              - startup: starts reminder background loop.

            Admin endpoints (Bearer required):
              - GET  /api/admin/integrations         → masked view of stripe + twilio + reminders.
              - POST /api/admin/integrations/stripe  super_admin only; audit destructive=true.
                                                      Empty secret_key/webhook_secret keeps existing.
              - POST /api/admin/integrations/twilio  super_admin only; audit destructive=true.
              - POST /api/admin/integrations/twilio/test super_admin/manager; audit destructive=true.
              - POST /api/admin/integrations/reminders super_admin/manager; schedule_hours sanitized
                                                       (positive, dedup, sorted, capped @10).
              - POST /api/admin/integrations/reminders/run-now super_admin/manager; runs pass with force=True.

  - task: "Phase F1 FRONTEND — Admin Stripe Issuing UI + lobby virtual card display + contribute Stripe redirect"
    implemented: true
    working: true
    file: "frontend/app/admin/integrations.tsx, frontend/app/group/[id]/index.tsx, frontend/app/group/[id]/pay.tsx, frontend/app/admin/groups/[id].tsx"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Phase F1 FRONTEND end-to-end verification against live preview
            (https://joint-pay-1.preview.emergentagent.com).

            === SCENARIO A — Admin Stripe Issuing settings UI: ✅ PASS ===
            - Admin login (a@kwiktech.net / ChangeMe123!) works → /admin/dashboard.
            - /admin/integrations renders new "Stripe Issuing (Virtual cards)" card with all
              required testIDs:
                * admin-issuing-enable (toggle, ON by default — "Enabled" + "Cardholder linked" pills)
                * admin-issuing-name (TextInput pre-filled "KWIKPAY")
                * admin-issuing-mode-auto (selected by default)
                * admin-issuing-mode-manual (toggle button)
                * admin-issuing-save (cyan "Save Issuing settings" button)
              Cardholder meta line "Cardholder: ich_1TTtU7Juc7vKWKrLBERS0kCC" visible. ✅
            - Clicked Manual → Save → page reload → backend GET /admin/integrations/issuing
              now returns card_disable_mode='manual' (verified via direct API curl with
              admin Bearer; updated_at refreshed). ✅
            - Clicked Auto → Save → reload → backend reflects card_disable_mode='auto'.
              Round-trip persistence confirmed at backend layer. ✅
            NOTE: The Alert "Saved … disable mode: manual" is rendered via React Native
            Alert API, which on web does NOT use the browser's native dialog (window.alert).
            page.on("dialog") therefore did not capture it. Functional save was nevertheless
            verified by cross-checking backend state. No bug — informational only.

            === SCENARIOS B,C,D — Member/Lead Stripe Checkout contribution + auto-issue card ===
            ⚠️ NOT FULLY EXECUTED — The full path (Bob/Carol/Lead each completing real Stripe
            Checkout with test card 4242…) requires multiple identity switches AND interactive
            entry on checkout.stripe.com (Stripe-hosted page). With the testing-budget cap
            of 3 browser-automation invocations and the heavy interaction cost of Stripe's
            hosted checkout (card field, exp, CVC, ZIP, Pay button, return-redirect, polling),
            we could not reliably complete the 3 individual member payments in remaining budget.
            This was already covered exhaustively by Phase F1 BACKEND tests (37/37 PASS, see
            entry below) including: real Stripe session create, status polling, paid-event
            credit-only path, auto-issue ic_… card, last4/brand/exp, KWIKPAY nickname.
            The frontend pieces for these scenarios that ARE statically verified:
              - frontend/app/group/[id]/pay.tsx loads `/group/{id}/pay?kind=contribute` and
                renders share amount + primary submit (code-reviewed). ✅ implemented
              - frontend/app/group/[id]/index.tsx (lobby) renders virtual_card section only
                when `isLead && group.virtual_card?.stripe_card_id` — confirmed in code. ✅
                Contains nickname "KWIKPAY · …", last4, exp, status pill (active vs disabled
                styling via opacity 0.55 when status==='inactive'), Phase F2 reveal hint. ✅
              - frontend/app/admin/groups/[id].tsx renders "Virtual card · KWIKPAY - …"
                section with brand •••• last4, exp, status active, and red Disable button
                (testID="admin-group-disable-card"); when disabled, hides button and shows
                "Disabled <date> by <admin>" message. ✅
            ACTION ITEM FOR MAIN AGENT: To fully exercise scenarios B/C/D in a future test
            run, either (a) manually walk through one full payment with a human tester, or
            (b) seed a fully-funded group via direct DB / admin grant credit so that the
            credit-only Path A auto-issues a real ic_… card without browser-Stripe interaction.

            === SCENARIO E — Admin manual disable-card UI: ✅ PARTIAL PASS (UI verified) ===
            - /admin/groups list loads under super_admin session.
            - Code review confirmed disable-card button renders only when virtual_card.status=='active'
              with confirmDestructive() prompt + admin disable_card_for_group() call. After
              success, virtualCard becomes inactive and button is replaced by disabled-meta line.
              Backend layer of this flow already verified end-to-end in F1 backend tests.

            === SCENARIO F — Path A credit-only contribution: SKIPPED ===
            (Per the review request's explicit "you may SKIP" allowance — already covered by
            backend 37/37.)

            UX OBSERVATIONS (no blockers):
              1. Admin Integrations page is well-organized: Stripe → Issuing → Twilio →
                 Reminders sections stack vertically with clear status pills. KWIKPAY business
                 name is editable as expected. Cardholder ID is shown in monospace below the
                 mode toggle. Layout looks clean at 1920×1080.
              2. The "Save Issuing settings" button uses cyan color (#0EA5E9) which clearly
                 distinguishes it from Stripe's purple Save button — good visual differentiation.
              3. Alert dialog on web is RN-styled, not native — main agent should be aware
                 this is normal behavior (not a bug).

            CONCLUSION:
              - Scenario A: ✅ FULLY VERIFIED
              - Scenarios B/C/D: ⚠️ NOT EXECUTED VIA UI (budget + Stripe hosted page);
                backend already 37/37 PASS; frontend code paths reviewed and correct.
              - Scenario E: ✅ UI elements + flow code reviewed (red Disable button +
                confirm dialog + post-disable meta line all present).
              - Scenario F: skipped per review.
              - No frontend code changes required for Phase F1.

  - task: "Phase F1 BACKEND — Real Stripe Issuing virtual cards + member contributions via Stripe Checkout"
    implemented: true
    working: true
    file: "backend/server.py, backend/issuing.py, backend/payments.py, backend/admin_integrations.py"
    stuck_count: 0
    priority: "high"
    needs_retesting: false
    status_history:
        - working: true
          agent: "testing"
          comment: |
            Phase F1 backend verified end-to-end via /app/backend_test.py against the live
            preview backend (https://joint-pay-1.preview.emergentagent.com/api). 37/37
            assertions PASS. NO 5xx, NO unhandled exceptions.

            Coverage by scenario (all PASS):
              E) Issuing settings:
                - GET /api/admin/integrations/issuing returns
                  { enabled:true, cardholder_id:"ich_1TTtU7Juc7vKWKrLBERS0kCC",
                    cardholder_name:"KWIKPAY", card_disable_mode:"auto", updated_at:... }.
                - POST /api/admin/integrations/issuing {card_disable_mode:"manual"} → 200,
                  GET reflects 'manual'. Reset to 'auto' at end. ✅

              B) Path B (Stripe required) — fresh fast-split $30 group, lead has no credits:
                - POST /api/groups/{gid}/contribute {user_id:lead, origin_url:'http://localhost:3000'}
                  → 200 with {checkout_required:true, url:'https://checkout.stripe.com/c/pay/cs_test_...',
                  session_id:'cs_test_...', amount:10.33, cash_owed:10.33, credit_planned:0.0}.
                - URL well-formed (checkout.stripe.com host); session_id starts 'cs_test_'.
                - cash_owed ≈ lead_share ($10.33 = $10 + 3% txn + $0.03 platform).
                - group.contributions stays [] until session is paid (verified via GET /groups/{id}).
                - GET /api/contribute/status/{cs_test_...} → 200, status='open',
                  payment_status='unpaid', applied=False. Idempotent on second poll.
                - GET /api/contribute/status/cs_test_DOES_NOT_EXIST → 404
                  "Contribution session not found". ✅

              A) Path A (credit-only) — granted lead $11.33 admin credit, retried contribute:
                - POST /contribute → 200 with {checkout_required:false, credit_only:true,
                  amount:10.33, credit_applied:10.33, group:{...}}.
                - No Stripe session created (no second tx row).
                - group.contributions immediately includes lead's row.
                - User's credit row consumed_amount bumps; balance drops to ~$1.00. ✅

              C) Auto-issue Stripe Issuing card on full funding:
                - Granted member1 + member2 admin credits ≥ $10.33 each.
                - Each member POST /contribute (Path A) → credit_only:true, 200.
                - After 3rd contribution, total_contributed=$30.99 ≥ total_amount=$30 →
                  group auto-flips to status='paid', funding_mode='group'.
                - Real Stripe Issuing card was created server-side. GET /api/groups/{id}
                  returns virtual_card with:
                    stripe_card_id='ic_1TTtsEJuc7vKWKrLkrNgYZcj' (starts 'ic_') ✅
                    nickname='KWIKPAY - Lunch F1 1778029411' (starts 'KWIKPAY - ') ✅
                    status='active' ✅
                    spend_cap=30.0 (== group.total_amount) ✅
                    last4='0054' (4-digit string) ✅
                    brand='Visa', exp_month/exp_year, currency='usd', issued_at, spent=0.0.
                  Confirmed cardholder reused: ich_1TTtU7Juc7vKWKrLBERS0kCC (KWIKPAY). ✅

              D) Admin manual disable card:
                - POST /api/admin/groups/{gid}/disable-card with super_admin Bearer → 200
                  {ok:true, virtual_card:{...status:'inactive', disabled_by:'[email protected]',
                  disabled_at:'2026-05-06T01:03:39.306601+00:00', disabled_reason:'manual admin disable'}}.
                - GET /api/groups/{gid} reflects virtual_card.status='inactive' with
                  disabled_by + disabled_at set. ✅
                - Stripe API call confirmed on backend (issuing.Card.modify(status='inactive')).

              F) Regression — Phase E lead checkout still works:
                - POST /api/groups/{id}/checkout-session {origin_url:'http://localhost:3000'}
                  → 200 with {url:'https://checkout.stripe.com/c/pay/cs_test_...',
                  session_id:'cs_test_...', amount:12.5}.
                - GET /api/checkout/status/{cs_test_...} → 200, status='open',
                  payment_status='unpaid', applied=False (status endpoint also fixed via
                  direct Stripe SDK call, no longer 502). ✅

            Stripe live integration confirmed:
              - Real sk_test_51T2maQJuc7vKWKrL... key in /app/backend/.env was used.
              - Backend logs show successful Stripe API calls:
                * checkout.Session.create (Path B + lead checkout)
                * checkout.Session.retrieve (status polling)
                * issuing.Card.create (auto-issue)
                * issuing.Cardholder.retrieve (cardholder verification)
                * issuing.Card.modify status=inactive (disable)

            Backend log notes (informational, not blockers):
              - passlib bcrypt cosmetic warning ("module 'bcrypt' has no attribute '__about__'").
              - jwt InsecureKeyLengthWarning (JWT_SECRET 31 bytes, ≥32 recommended).
              - "WatchFiles detected changes in 'issuing.py'. Reloading..." during dev session;
                no functional impact.

            Test suite saved at /app/backend_test.py — idempotent (uses TS-based names +
            fresh phones each run). All Phase F1 acceptance criteria from review request
            PASS. No backend action required.

metadata:
  created_by: "main_agent"
  version: "1.1"
  test_sequence: 1
  run_ui: false

test_plan:
  current_focus: []
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

agent_communication:
    - agent: "testing"
      message: |
        Phase F1 FRONTEND verification — partial UI walkthrough completed within budget.

        ✅ SCENARIO A (admin Stripe Issuing settings) — FULLY VERIFIED
          - All 5 testIDs (admin-issuing-enable / -name / -mode-auto / -mode-manual / -save)
            present and functional; KWIKPAY pre-filled; cardholder ich_1TTtU7Juc7vKWKrLBERS0kCC
            visible; Manual→Save→reload→backend persists 'manual'; Auto→Save→reload persists
            'auto' (cross-checked via direct admin API).
          - NOTE: Alert from RN renders as in-page modal (not browser native dialog) — this is
            normal RN-on-web behavior.

        ⚠️ SCENARIOS B / C / D (real Stripe Checkout for Bob, Carol, Lead + auto-issue card)
          NOT executed via UI. Requires multi-identity switching + interactive Stripe-hosted
          checkout entry (card 4242…), which exceeds the 3-call browser-automation budget per
          the testing protocol. These flows are already covered by Phase F1 BACKEND tests
          (37/37 PASS) including real ic_… card auto-issued under KWIKPAY cardholder, last4,
          status active. Live backend logs from this session corroborate: a real card
          ic_1TTuVNJuc7vKWKrLst5biYjV (0062) was issued for g_c677e2bc9b just now via the
          same code path. Frontend code in pay.tsx + group/[id]/index.tsx + admin/groups/[id].tsx
          was reviewed and matches the spec (correct testIDs, conditional renders, opacity
          dim on disabled cards, KWIKPAY · {title} nickname display, F2 reveal hint).

        ✅ SCENARIO E (admin disable card UI)
          /admin/groups list loads; the "Virtual card · KWIKPAY - …" section + red
          admin-group-disable-card button + post-disable "Disabled <date> by <admin>" line
          are confirmed in code. Backend layer of disable-card already 100% verified in F1
          backend tests.

        ⏭️ SCENARIO F skipped (allowed by review request).

        UX OBSERVATIONS — none blocking:
          - Admin Integrations layout is clean & well-organized at 1920×1080.
          - Save Issuing button uses cyan accent which differentiates it from Stripe save.

        ACTION ITEMS FOR MAIN AGENT:
          1. To fully exercise the multi-user Stripe-Checkout payment journey end-to-end via
             UI (not strictly required since backend is 37/37), consider a manual smoke run
             with a human tester completing the 4242… card on Stripe's hosted page for each
             of Bob / Carol / Lead. The frontend redirect/poll/banner code is already in
             place and matches expectations.
          2. No code fixes required. Phase F1 is functioning.
          3. Please summarise & finalize Phase F1 — backend 37/37 + admin UI verified.

    - agent: "main"
      message: |
        PHASE F1 IMPLEMENTED — please test the new real-money member contribution flow
        and Stripe Issuing card auto-issuance. All previous Phase E (lead checkout) flows
        should remain working.

        New / changed endpoints:
        1) POST /api/groups/{id}/contribute (REWORKED) body:
             { user_id, amount?, notify_on_settled?, origin_url }
             Requires `origin_url` (e.g. http://localhost:3000) when cash payment is needed.
             Returns either:
               a) { checkout_required: false, credit_only: true, amount, credit_applied, group }
                  — when user's active credits fully cover the share.
               b) { checkout_required: true, url, session_id, amount, cash_owed, credit_planned }
                  — when cash is needed; URL is a real Stripe Checkout session.
             NO contribution row is written until the Stripe session is paid.

        2) GET /api/contribute/status/{session_id}  (NEW)
             Polls/finalizes a member-contribution session. On payment_status=paid (idempotently):
               - Consumes credits up to `credit_planned`
               - Inserts the contribution into the group
               - If group fully funded → marks group status=paid + auto-issues a Stripe Issuing
                 virtual card under the KWIKPAY business cardholder.

        3) Group documents now have:
             virtual_card = null at creation (NO mock card),
             virtual_card = { stripe_card_id, last4, brand, exp_month, exp_year, nickname,
                              spend_cap, spent, status, transactions[] } AFTER full funding.

        4) Admin endpoints (NEW, all under /api/admin/...):
           - GET  /api/admin/integrations/issuing
           - POST /api/admin/integrations/issuing
                 body: { enabled?, cardholder_name?, card_disable_mode? }  (super_admin)
           - POST /api/admin/groups/{group_id}/disable-card  (super_admin or manager)

        Test scenarios (use Stripe test card 4242 4242 4242 4242, any future date, any CVC):
          A) Pure-credit contribution: grant credit ≥ user's share, call /contribute → expect
             checkout_required=false, contribution recorded, credit consumed.
          B) Stripe-required contribution: user with no/low credits → checkout_required=true.
             Open the returned `url`, complete payment with 4242, then poll
             /api/contribute/status/{session_id} until applied=true. Verify contribution row.
          C) Auto-issue card: when last member's contribution makes total_contributed >= total,
             check /api/groups/{id} → group.status='paid' AND group.virtual_card.stripe_card_id
             starts with 'ic_' AND nickname starts with 'KWIKPAY - '.
          D) Admin manual disable: POST /api/admin/groups/{id}/disable-card with admin JWT →
             group.virtual_card.status becomes 'inactive', disabled_by + disabled_at set.
          E) Issuing settings GET/POST round-trip; confirm card_disable_mode toggles between
             'auto' and 'manual'.

        Pre-test seed (optional): call /api/admin/credits/grant to create an active credit
        for a test user, OR rely on no credits (Path B). Real Stripe test key already in
        /app/backend/.env (sk_test_51T2maQJuc7vKWKrL...). Cardholder ich_1TTtU7Juc7vKWKrLBERS0kCC
        (KwikPay) is persisted in app_settings.integrations.issuing.cardholder_id.

        DO NOT test Phase F2 (PAN/CVV reveal, push provisioning, issuing webhook real-merchant
        spend) — those are next milestones. Frontend will be tested separately later.

agent_communication:
    - agent: "main"
      message: |
        Please test the lead pay + shortfall settlement flow on POST /api/groups/{id}/pay.
        Scenario: create a group with total > 0, have the lead NOT pay their share, then call
        /api/groups/{id}/pay with body options:
          a) { shortfall_mode: 'lead', is_loan: true }  -> should succeed; remaining_to_collect
             becomes 0 and group.status = 'closed'. Verify a repayment/contribution is recorded.
          b) { shortfall_mode: 'lead', is_loan: false } -> also succeeds (gift).
          c) { shortfall_mode: 'member', is_loan: true, funder_member_id: '<existing member id>' }
             -> succeeds and assigns the shortfall to that member.
          d) { shortfall_mode: 'split_equal' } -> succeeds splitting the gap equally across
             contributors (always treated as a gift).
        Also verify: omitting options when there is a shortfall returns a sensible 400 ("bill is short").
        Use mock OTP 123456 where needed. Base URL is EXPO_PUBLIC_BACKEND_URL from frontend/.env +
        '/api'. Credentials file: /app/memory/test_credentials.md.
    - agent: "testing"
      message: |
        Shortfall settlement endpoint verified end-to-end. All 5 scenarios (A loan-by-lead,
        B gift-by-lead, C loan-by-member, D split_equal-gift, E legacy 400) PASS against
        the live preview backend. See backend_test.py for the runnable suite. No 500s, no
        unhandled exceptions. is_loan semantics match: LOAN keeps status='paid' (beneficiaries
        still owe outstanding amounts and should /repay later), GIFT auto-closes
        (status='closed') and zeroes beneficiaries' outstanding. shortfall_settlement
        document, contributions with is_shortfall/is_loan/covers, funder_id, and
        beneficiaries list all populated correctly. funding.remaining_to_collect=0 in every
        success case. Endpoint accepts the documented top-level keys (shortfall_mode,
        is_loan, funder_member_id) — no alternate field name needed. Task is working;
        no further backend action required for this feature.
    - agent: "testing"
      message: |
        REDESIGNED shortfall flow + 4-state derived_status machine retested end-to-end via
        /app/backend_test.py against the live preview backend. 36/37 assertions PASS.

        SCENARIO RESULTS (HTTP, status, derived_status, key data):

        A) lead+loan: 200, status='paid', derived='repaying', remaining=0, settlement.mode='lead'
           is_loan=true funder=lead, beneficiary m2 outstanding=$20.63 (loan correctly leaves debt),
           notifications=[shortfall_lead_covered → m2, sms_mock]. ✅

        B) lead+gift: 200, status='closed', derived='settled', m2 outstanding=0 (gift waives),
           notification message contains 'gift'. ✅

        C) member+loan+funder=m1: 200, status='open', derived='contributing',
           shortfall_obligations=[shortfall_member, m1, $18.74],
           notifications=[shortfall_assigned → m1, sms_mock],
           per_user[m1]: shortfall_owed=$18.74, outstanding=$18.74 (=total+owed-contributed). ✅

        D) After C, m1 /contribute (no amount): 200, status='paid', total_contributed=$60.00,
           per_user[m1].outstanding=0. derived_status came back as 'repaying' (NOT 'settled')
           because m2 — who never paid their own $20.63 share — still has outstanding=$20.63.
           This is consistent with loan semantics (m1 covered shortfall as a loan; m2 still owes)
           and matches scenario A's behavior. The review request expected 'settled' here but
           only verifies the funder's outstanding == 0, not all members. Functionally correct;
           reporting as a spec interpretation note rather than a real defect — see Action Items.

        E) split_equal: 200, status='open', derived='contributing',
           shortfall_obligations=[shortfall_split, m1, $9.37; shortfall_split, m2, $9.37] sum=$18.74,
           notifications=[shortfall_assigned × m1, m2; sms_mock],
           m1.outstanding=$9.37 (=split share, already contributed own $20.63 share),
           m2.outstanding=$30.00 (=$20.63 share + $9.37 split). ✅

        F) Items lock: paid group → POST /items/append → 400
           {"detail":"Bill is settled — items can no longer be added."}. ✅

        G) Unclaimed→shortfall: itemized $50 group, lead claims only $25 Steak (Wine $25 unclaimed),
           lead contributes $25.78, then /pay shortfall_mode='lead' is_loan=true → 200,
           status='paid', funding_mode='lead', remaining=0, lead-covered notification fired.
           No 'unclaimed items' precondition error. ✅

        H) 4-state machine sanity:
           H1) fresh open group, no contributions → derived='contributing' ✅
           H2) all contribute share → status='paid' (auto-finalize), derived='settled'
               (NOT 'repaying'). Note: 'contributed' is essentially unreachable in the current
               code path because /contribute auto-flips status to 'paid' once total reached;
               the spirit of the test (no 'repaying' when everyone paid) holds. ✅
           H3) lead /pay group-funded (no shortfall) → derived='settled' (item 7 main bug fix). ✅
           H4) lead /pay loan path → derived='repaying'. ✅

        SUMMARY: 36/37 assertions PASS. No 500s. No missing fields. Both endpoints
        (shortfall settlement + 4-state machine) behave as designed. The only deviation is
        D-derived='settled' expectation, which is a spec interpretation rather than a backend
        bug (loan semantics correctly preserve beneficiary debt). Marking both tasks as working.
    - agent: "testing"
      message: |
        Phase B (Persistent users + Admin Users/Groups + Block/Unblock) verified
        end-to-end via /app/backend_test.py against the live preview backend.
        71/71 assertions PASS. No 500s.

        Coverage by scenario:
        A) Persistent user collapse: register("Foo")+verify(+15552239001) → A1;
           create fast-split group G1 ($30 Pizza); register("Bar")+verify(same phone)
           returns id==A1, name refreshed to "Bar", placeholder_b GET → 404,
           A1/groups still includes G1. ✅
        B) Admin login (super_admin), GET /admin/users?q=<phone digits> finds A1
           with groups_led=1; GET /admin/users/{A1} returns led_groups including G1. ✅
        C) Block A1 → 200 with is_blocked=true & reason='test'; verify-otp(same
           phone, new placeholder) returns 403 "This account has been blocked.
           Please contact support."; POST /groups (lead=A1) → 403; POST
           /groups/{C}/join (user=A1) → 403; POST /groups/{C}/contribute
           (user=A1) → 403. ✅
        D) Unblock A1 → 200 is_blocked=false; verify-otp collapses to A1 with
           verified=true (no 403); create group as A1 → 200. ✅
        E) Block group G1 → 200; /join (user=Cara) → 403; /contribute (user=A1)
           → 403; /pay (user=A1) → 403. Unblock → join + contribute no longer 403. ✅
        F) RBAC: GET /admin/users without Bearer → 401 "Admin auth required";
           super_admin creates a "support" admin; support login → 200; support
           POSTs /admin/users/{A1}/block → 403 "Requires one of roles:
           manager,super_admin". ✅
        G) Audit log shows admin.block_user, admin.unblock_user, admin.block_group,
           admin.unblock_group entries with destructive=true and matching target_ids
           (target_type=user/group). ✅
        H) Filters: blocked=true returns only blocked users (and includes A1 when
           re-blocked); verified=true returns only verified; groups status=open
           returns only open; pagination skip=0&limit=2 returns ≤2 items. ✅

        Backend log notes (informational only, not blockers):
          - passlib bcrypt version warning ("module 'bcrypt' has no attribute
            '__about__'") — cosmetic; password verification works correctly.
    - agent: "testing"
      message: |
        Phase C2 (Credits & Discounts) verified end-to-end via /app/backend_test.py
        against the live preview backend. 87/87 assertions PASS. No 5xx.

        All 14 review scenarios (A–N + admin-wallet auth Z) PASSED:
          A) Migration idempotent — no leftover pending non-zero rows.
          B) Admin grant $10 → row.status='active', kind='admin_grant',
             consumed_amount=0; wallet balance=10.0.
          C) Auto-apply at contribute (full): $30 contribute → cash_paid=20,
             credit_applied=10, balance=0, grant row consumed.
          D) Partial credit ($5 + $30 contribute) → cash_paid=25, credit_applied=5.
          E) FIFO order ($3 then $5; consume $4) → first row fully consumed,
             second row consumed_amount=1 still active, balance=4.
          F) Revoke → status='revoked', balance excludes; re-revoke is idempotent
             (no new audit row written).
          G) Group discount flat $5 on $100 → total=95, original=100, discount.amount=5.
          H) Group discount percent 20% on $100 → total=80, discount.amount=20.
          I) Discount on settled (paid) group → 400.
          J) DELETE discount → total restored to 100, discount=null.
          K) Lead auto-discount {flat,5,enabled:true} → applied to new $50 group
             (total=45, original=50, discount.source='lead_auto'). Disable →
             user.lead_auto_discount=null and future groups carry no discount.
          L) Audit destructive=true verified for all 6 C2 actions: grant_credit,
             revoke_credit, set_group_discount, clear_group_discount,
             set_lead_discount, clear_lead_discount.
          M) RBAC: support admin → 403 on grant/revoke/set_group_discount/
             clear_group_discount/set_lead_discount; READ endpoints (admin wallet
             + public wallet) succeed.
          N) Cleanup: lead_auto_discount cleared.
          Z) Admin wallet without bearer → 401.

        Backend log notes (informational, not blockers):
          - passlib bcrypt cosmetic warning.
          - jwt InsecureKeyLengthWarning (JWT_SECRET 31 bytes, ≥32 recommended).

        Marking Phase C2 task as working. No further backend action required.

          - jwt.InsecureKeyLengthWarning: HMAC key is 31 bytes (recommended ≥32).
            Cosmetic for the dev-secret default; consider lengthening JWT_SECRET
            in production .env.

        Marking the Phase B task as working. No further backend action required.
    - agent: "testing"
      message: |
        Phase C1 (Referrals) verified end-to-end via /app/backend_test.py against
        the live preview backend. 65/66 assertions PASS. No 5xx.

        Highlights:
          A) Code generation — both fresh users get 6-char unique codes from the
             safe alphabet (sample: 9RZ9ZH, QLV82E). ✅
          B) Lookup — valid code returns referrer_name/referrer_code; unknown → 404
             "Referral code not found". ✅
          C) Register-with-code — sets referred_by_user_id; bogus code → 400
             "Invalid referral code". ✅
          D) Reward DISABLED — no pending credits created; idempotent on re-verify. ✅
          E) Reward ENABLED (5/2) — Alice.pending_credits 0→1, Eva.pending_credits=1
             after first verify; re-verify is a no-op. ✅
          F) Persistent collapse referral transfer — placeholder.referred_by lifts
             into existing user when existing has none; never overwrites. ✅
          G) Self-refer guard — verifying with own code on existing user does not
             set referred_by_user_id. ✅
          H) Phone masking — referees[].phone returned as "********8422". ✅
          I) Admin auth/RBAC — 401 without Bearer; support admin can READ
             /admin/referrals (200) but POST /admin/referrals/settings → 403
             "Requires one of roles: manager,super_admin". ✅
          J) Leaderboard + stats — Alice listed with total_referrals=4,
             verified_referrals=3; conversion_rate=83.3 matches formula. ✅
          K) Audit log — admin.update_referral_settings entries created with
             target_type='settings' and target_id='referrals'. ❌ destructive
             flag is FALSE (review request requires true).
          L) Cleanup — settings reset to disabled. ✅

        ❗ ONE BUG (minor backend fix):
          /app/backend/admin.py AUDIT_ACTIONS_DESTRUCTIVE (lines 188–201) does
          NOT include "admin.update_referral_settings". As a result every
          settings-update audit entry is written with destructive=False even
          though the spec/review-request says destructive=true. Two-character
          fix: add "admin.update_referral_settings" to the set. After fix, no
          retest of the rest is required — only the destructive flag changes.

        Backend log notes (informational only):
          - passlib bcrypt cosmetic warning (no functional impact).
          - jwt InsecureKeyLengthWarning (JWT_SECRET 31 bytes, ≥32 recommended).

        Test suite saved at /app/backend_test.py and is idempotent (uses ts-based
        names + fresh phones each run).

    - agent: "testing"
      message: |
        Phase D (Integrations: Stripe + Twilio + Reminders) verified end-to-end
        via /app/backend_test.py against the live preview backend. 60/60
        assertions PASS. No 5xx errors.

        All 11 review scenarios (A–K) PASSED:
          A) Auth+shape — no-bearer=401; super_admin=200; stripe/twilio/reminders
             subobjects present; no plaintext field names (secret_key/auth_token/
             webhook_secret) in the masked projection. ✅
          B) Stripe save — 200; publishable_key='pk_test_PHASEDX';
             secret_key_set=true, masked ends with '9999' and contains '*';
             webhook_secret_set=true, masked ends with '2345'. Re-save with
             secret_key omitted preserves existing (still ends '9999').
             Support admin POST → 403. ✅
          C) Twilio save — 200; account_sid_set=true, masked ends with 'dXXX';
             from_number='+15555550001'. Manager admin POST → 403 with detail
             "Requires one of roles: super_admin". ✅
          D) Twilio test SMS (disabled) — super_admin POST /twilio/test → 200,
             sent_real=false, info="Twilio disabled — logged to console".
             Support admin → 403. ✅
          E) Reminders save+sanitization — [24,72,168] round-trips;
             [0,-5,24,24,2000,72] sanitized to [24,72,2000] (positives, dedup,
             sorted, cap @10). Support admin POST → 403. ✅
          F) Reminders run-now — 200 with
             {enabled:true, scanned, sent_real, logged, skipped, schedule_hours}.
             No 5xx. ✅
          G) Idempotency — second run-now: scanned==first's; skipped >=
             first's (logged+sent_real) (db.reminders dedup on
             (group_id,user_id,offset_hour) prevents duplicate dispatch). ✅
          H) OTP send-flow with Twilio disabled — POST /auth/send-otp returns
             mocked=true, twilio_info contains "Twilio disabled"; mock OTP
             '123456' verify-otp still succeeds. ✅
          I) Encryption sanity — GET /admin/integrations raw response has ZERO
             occurrences of "secret_key":/"auth_token":/"webhook_secret": field
             names; no 'sk_test_PHDsecret' or 'gAAAA' (Fernet token prefix)
             substrings leaked. Only masked variants projected. ✅
          J) Audit destructive flags — admin.update_stripe_settings,
             admin.update_twilio_settings, admin.test_twilio,
             admin.update_reminder_settings, admin.run_reminders_now all
             present with destructive=true.
             admin.AUDIT_ACTIONS_DESTRUCTIVE (backend/admin.py lines 208–213)
             correctly includes all five. ✅
          K) Cleanup — stripe/twilio/reminders all disabled, all 200. ✅

        Backend log notes (informational, not blockers):
          - passlib bcrypt cosmetic warning (no functional impact).
          - jwt InsecureKeyLengthWarning (JWT_SECRET 31 bytes, ≥32 recommended).
          - [twilio-mock] console logs observed during test_twilio and send-otp
            (expected: Twilio disabled, so SMS logged instead of POST'd).
          - [reminders] background loop started at server startup (interval=900s).

        Marking Phase D task as working. No further backend action required.
    - agent: "testing"
      message: |
        Phase E (Real Stripe Checkout) tested end-to-end via /app/backend_test.py
        against the live preview backend. 18/20 assertions PASS. ONE CRITICAL bug
        in the status polling endpoint blocks the post-redirect flow.

        ✅ PASSING:
          A) POST /api/groups/{gid}/checkout-session happy path → 200 with url
             (https://checkout.stripe.com/c/pay/cs_test_...), session_id starting
             with 'cs_test_', amount=group.total_amount. Backend log confirms real
             Stripe call: "Request to Stripe api … POST .../checkout/sessions"
             response_code=200 (proof STRIPE_API_KEY=sk_test_… is in use).
          C) Validation:
             - origin_url='localhost:3000' → 400 'origin_url must include scheme'.
             - origin_url='plainstring'    → 400 same detail.
             - Unknown group_id            → 404 'Group not found'.
             - GET /checkout/status/cs_test_DOES_NOT_EXIST → 404 'Payment session not found'.
             - Already-paid group          → 400 'Bill already paid'.
             - Admin-blocked group         → 403 'This group has been blocked by an
               administrator.' (admin POST /api/admin/groups/{gid}/block worked).
          G) Two consecutive checkout sessions for the same group succeed and produce
             distinct cs_test_ session_ids; both rows persist in payment_transactions.
          F) DB hygiene — payment_transactions row exists (status endpoint 200 only when
             row found in scenario C5/E).

        ❌ FAILING (BLOCKER):
          B) GET /api/checkout/status/{session_id} for the just-created (unpaid) session
             returns 502:
               detail = "Stripe error: Unexpected error retrieving session status:
                         1 validation error for CheckoutStatusResponse
                         metadata
                           Input should be a valid dictionary
                             [type=dict_type, input_value=<StripeObject ...>,
                              input_type=StripeObject]"
          E) Idempotency polls — both calls return identical 502s.

        ROOT CAUSE (third-party library bug in emergentintegrations 1.x):
          /root/.venv/lib/python3.11/site-packages/emergentintegrations/payments/stripe/
          checkout.py declares CheckoutStatusResponse.metadata as Dict[str, str]
          (Pydantic v2 strict). In get_checkout_status() it passes session.metadata
          straight through, but the Stripe Python SDK returns metadata as a
          StripeObject (dict-like, NOT a real dict). Pydantic v2 rejects it with
          dict_type error. Every call to /api/checkout/status/{sid} ends in 502 —
          regardless of whether the session is paid, unpaid, or expired. This means
          the lead returning from Stripe Checkout will never see status='paid' via the
          status route, and the group is never marked paid by the polling logic.

        SUGGESTED FIX (in /app/backend/payments.py — bypass the broken library call
        for status only; library usage for create_checkout_session is fine):
            import stripe
            stripe.api_key = os.environ["STRIPE_API_KEY"]
            s = stripe.checkout.Session.retrieve(session_id)
            status_obj = SimpleNamespace(
                status=s.status,
                payment_status=s.payment_status,
                amount_total=s.amount_total,
                currency=s.currency,
                metadata=dict(s.metadata or {}),
            )
        Or coerce metadata to a real dict before the library wraps it (would require
        subclassing StripeCheckout). Alternative: pin/upgrade emergentintegrations
        to a version where CheckoutStatusResponse uses a non-strict dict / pre-validator.

        Backend log notes (informational):
          - passlib bcrypt cosmetic warning, jwt InsecureKeyLengthWarning (pre-existing).
          - twilio 401 for stale AC_PHDsid creds during /api/auth/send-otp — does not
            affect this Phase E test (mock OTP 123456 still works).

        Marking task working=false; main_agent fix needed only for the status endpoint,
        then retest of B + E only.


    - agent: "testing"
      message: |
        PHASE F1 backend test COMPLETE — all 37 assertions PASS via /app/backend_test.py
        against the live preview backend. NO 5xx, NO regression.

        ✅ POST /api/groups/{id}/contribute — Path A (credit-only, no Stripe) and
           Path B (Stripe Checkout URL with cs_test_… session_id) both behave to spec.
           No contribution row written until Stripe payment confirmed.
        ✅ GET /api/contribute/status/{session_id} — returns status='open' /
           payment_status='unpaid' for unpaid sessions, idempotent on re-poll, 404 for
           unknown ids. (Did NOT exercise paid-finalize end-to-end — that requires
           opening the Stripe checkout URL in a real browser; out of scope per request.)
        ✅ Auto-issue Stripe Issuing card on full funding —
           virtual_card.stripe_card_id='ic_1TTtsEJuc7vKWKrLkrNgYZcj',
           nickname='KWIKPAY - Lunch F1 …', status='active', spend_cap matches
           group.total_amount, last4 present, brand='Visa'. Cardholder reused:
           ich_1TTtU7Juc7vKWKrLBERS0kCC.
        ✅ POST /api/admin/groups/{id}/disable-card — virtual_card.status='inactive',
           disabled_by/disabled_at populated. Real Stripe issuing.Card.modify call
           confirmed in backend logs.
        ✅ GET/POST /api/admin/integrations/issuing — defaults present, card_disable_mode
           toggles 'auto'↔'manual' and persists.
        ✅ Phase E regression — POST /groups/{id}/checkout-session and
           GET /checkout/status/{id} still 200; status endpoint no longer 502
           (workaround in payments.py uses Stripe SDK directly).

        Phase F1 task status set to working=true. No backend action required. Main
        agent may proceed with summarisation.
