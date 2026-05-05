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

metadata:
  created_by: "main_agent"
  version: "1.1"
  test_sequence: 1
  run_ui: false

test_plan:
  current_focus:
    - "Shortfall settlement endpoint — POST /api/groups/{id}/pay with shortfall_settlement options"
  stuck_tasks: []
  test_all: false
  test_priority: "high_first"

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