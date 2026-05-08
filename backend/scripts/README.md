# SquadPay — Admin Recovery Tools

Two parallel ways to recover an admin account when normal sign-in / password-reset email doesn't work. Use whichever path matches your access:

| Access you have                        | Use                                        |
|----------------------------------------|--------------------------------------------|
| Shell on the deployed backend          | **CLI scripts** (this directory)           |
| Only env-var dashboard + curl/Postman  | **HTTP recovery endpoints** (`/api/admin/_recovery`) |

Both paths do the same things, write the same audit-log entries (`admin_recovery.*` / `admin_password_reset.cli_emergency`), and are safe to use repeatedly.

---

## When to reach for these

- Admin account is locked (`failed_logins >= 3` → 423 LOCKED responses).
- The reset email never arrives (Gmail same-domain routing, missing SMTP env, blocked sender, etc.).
- You're not even sure the admin record exists in the deployed DB.
- You inherited the deployment and need to seed the very first super-admin.

These tools **bypass** the email step — they reset the password directly in MongoDB.

---

## Path A — CLI scripts (shell access required)

### 🩺 `admin_diagnose.py` — read-only health check

```bash
cd /app/backend
python scripts/admin_diagnose.py admin@squadpay.us
```

Prints, for the given email:

- Effective `EMAIL_*` SMTP config (sender redacted, password length only).
- A **same-domain routing warning** if `EMAIL_FROM` and the recipient share a domain (Gmail Workspace gotcha).
- Admin record state: `id`, `role`, `is_active`, `failed_logins`, `locked_until`, `force_password_reset`, timestamps.
- Last 10 password-reset-token requests for this admin, with hashed-token previews + used/unused state.
- Last 15 audit-log entries — look for `email_sent ✅`, `email_skipped ⚠️`, `email_failed ⚠️`, `login_locked 🔒`.
- Number of active admin sessions.

Read-only — makes **no** changes.

### 🔑 `admin_reset_password.py` — emergency password reset

```bash
cd /app/backend

# Set a known password (works immediately — no further reset required)
python scripts/admin_reset_password.py admin@squadpay.us 'NewPass#2026'

# Or let the script generate a strong random one and print it once
python scripts/admin_reset_password.py admin@squadpay.us

# Or also force a password change on first login (post-recovery hardening)
python scripts/admin_reset_password.py admin@squadpay.us 'NewPass#2026' --force-reset
```

What it does (idempotent — safe to re-run):

1. **Upserts** the admin (creates a `super_admin` if missing, updates if found).
2. Sets the new bcrypt password hash.
3. Clears `failed_logins`, `locked_until`, `lock_round`.
4. Sets `force_password_reset=false` (or `true` with `--force-reset`).
5. Marks all outstanding `admin_password_reset_tokens` as used.
6. Deletes all rows in `admin_sessions` for this admin → forces re-login on every device.
7. Writes `admin_password_reset.cli_emergency` to the audit log.

After it finishes, sign in at `https://www.squadpay.us/admin/login` with the printed password.

---

## Path B — HTTP recovery endpoints (no shell needed)

When you only have access to the deploy dashboard's env vars + a way to make HTTPS requests (curl, Postman, browser DevTools).

### 🔓 1. Activate

There are **two** ways to activate the recovery endpoints — pick whichever matches your access:

#### Option A — Dedicated env var (preferred when you can add custom env vars)

In the backend deployment dashboard, set:

```
ADMIN_RECOVERY_TOKEN=<a long random string, 24+ chars>
```

> Tip: generate one with `python -c 'import secrets;print(secrets.token_urlsafe(32))'` locally, or any password generator.

**Redeploy the backend.** The endpoints become available.

#### Option B — Reuse `JWT_SECRET` as the gate (no new env var needed)

If your deployment platform doesn't let you add new custom env vars (e.g., Emergent's "Edit Custom keys" dialog only allows editing the keys declared at initial deploy), you can use the **already-configured** `JWT_SECRET` as the recovery token:

1. Open your deployment dashboard's Custom Keys section.
2. Click the 👁 reveal icon on `JWT_SECRET` and copy its value.
3. Use that value as the `X-Recovery-Token` header in the calls below.
4. **After recovery, ROTATE `JWT_SECRET`** in the same dashboard. This:
   - Invalidates the recovery gate (no one can replay the call).
   - Invalidates all currently-issued admin JWTs → forces every admin to re-login (which is healthy hygiene after a recovery event anyway).

The endpoint priority-order is `ADMIN_RECOVERY_TOKEN` first, then `JWT_SECRET`. Either matching value unlocks the endpoint. The response includes `recovered_via: "admin_recovery_token"` or `"jwt_secret_fallback"` so the audit trail makes the gate explicit.

#### State machine

| Both env vars unset/short | `503 Service Unavailable` |
| Either set + correct token sent | `200 OK` |
| Either set + wrong token sent | `401 Invalid recovery token` |

`MIN_TOKEN_LEN` is 24 chars. Tokens shorter than that are rejected at server boot to avoid weak-secret accidents.

### 🩺 2. Diagnose (read-only)

```bash
curl -sS "https://<your-backend-domain>/api/admin/_recovery/diagnose?email=admin@squadpay.us" \
  -H "X-Recovery-Token: <ADMIN_RECOVERY_TOKEN>" | jq
```

Returns JSON with the same fields as the CLI diagnose script: `email_config`, `admin`, `recent_reset_tokens`, `recent_audit_log`, `active_sessions`, `warnings[]`. Read-only.

### 🔑 3. Reset password

```bash
# Server generates a strong random password
curl -sS -X POST "https://<your-backend-domain>/api/admin/_recovery/reset-password" \
  -H "X-Recovery-Token: <ADMIN_RECOVERY_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@squadpay.us"}' | jq

# Or set your own password
curl -sS -X POST "https://<your-backend-domain>/api/admin/_recovery/reset-password" \
  -H "X-Recovery-Token: <ADMIN_RECOVERY_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@squadpay.us","new_password":"NewPass#2026"}' | jq

# Add force_reset:true if you want to require a change on first sign-in
curl -sS -X POST "https://<your-backend-domain>/api/admin/_recovery/reset-password" \
  -H "X-Recovery-Token: <ADMIN_RECOVERY_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@squadpay.us","new_password":"NewPass#2026","force_reset":true}' | jq
```

Successful response (one-shot — copy the password before closing the window):

```json
{
  "ok": true,
  "admin_id": "ad_xxxxxxxxxx",
  "email": "admin@squadpay.us",
  "created": false,
  "force_password_reset": false,
  "password": "G3ner@tedP4ssw0rd!",
  "password_generated": true,
  "outstanding_tokens_invalidated": 1,
  "sessions_killed": 0,
  "sign_in_url": "https://www.squadpay.us/admin/login",
  "note": "Use this password to sign in immediately."
}
```

The same DB mutations + audit-log entry as the CLI path are applied. Audit action: `admin_recovery.reset_password`.

### 🔒 4. Deactivate (REQUIRED step!)

Once you're back in:

**If you used `ADMIN_RECOVERY_TOKEN`:**
1. Remove `ADMIN_RECOVERY_TOKEN` from the deployment env vars.
2. **Redeploy.** Endpoints will return `503` again.

**If you used the `JWT_SECRET` fallback:**
1. Open your deployment dashboard's Custom Keys section.
2. Click into `JWT_SECRET` and replace its value with a fresh random string (32+ chars).
3. **Save / redeploy.** This single rotation does two things at once:
   - Invalidates the recovery gate (the value you used is no longer valid).
   - Invalidates every active admin JWT → forces re-login with the new password.

Leaving the recovery gate active is equivalent to leaving an unauthenticated password-reset endpoint open. Don't.

---

## Endpoint quick-reference

| Method | Path                                          | Auth                       | Notes                          |
|--------|-----------------------------------------------|----------------------------|--------------------------------|
| GET    | `/api/admin/_recovery/diagnose?email=…`       | `X-Recovery-Token` header  | Read-only                      |
| POST   | `/api/admin/_recovery/reset-password`         | `X-Recovery-Token` header  | JSON body: `email`, `new_password?`, `force_reset?` |

Both return `503` when `ADMIN_RECOVERY_TOKEN` is unset (or shorter than 24 chars), `401` on token mismatch.

---

## Common warnings printed by `diagnose` and what they mean

| Warning                                                              | Likely fix                                                                       |
|----------------------------------------------------------------------|----------------------------------------------------------------------------------|
| `EMAIL_PASSWORD is not set`                                          | Add the SMTP env vars in the deploy dashboard + redeploy.                        |
| `Same-domain routing: sender and recipient share '<domain>'`         | Switch `EMAIL_FROM` to a different domain (e.g. a Postmark / SendGrid sender), or check Spam + All Mail in the recipient's mailbox. |
| `No admin record found`                                              | Run reset-password endpoint/script — it'll seed a `super_admin`.                 |
| `is_active=False`                                                    | Re-enable via reset-password endpoint/script (it sets `is_active=True`).         |
| `Account is locked until <iso>`                                      | Reset-password endpoint/script clears `failed_logins`/`locked_until`.            |

---

## Audit log actions you'll see

| Action                                  | Origin                              |
|-----------------------------------------|-------------------------------------|
| `admin_password_reset.email_sent` ✅    | Normal forgot-password flow worked. |
| `admin_password_reset.email_skipped` ⚠️ | `EmailNotConfigured` — env missing. |
| `admin_password_reset.email_failed` ⚠️  | SMTP rejected (bad app password / blocked IP / etc.). |
| `admin_password_reset.completed`        | A user successfully completed `/admin/reset-password` from the email link. |
| `admin_password_reset.cli_emergency`    | `scripts/admin_reset_password.py` was run.   |
| `admin_recovery.diagnose`               | `_recovery/diagnose` was hit with a valid token. |
| `admin_recovery.reset_password`         | `_recovery/reset-password` was hit with a valid token. |

---

## Safety notes

- The HTTP recovery endpoints use `hmac.compare_digest` for token comparison (timing-safe).
- Tokens shorter than 24 characters are rejected at server boot to avoid weak-secret accidents.
- Every successful AND attempted call leaves an audit-log entry that includes the requesting IP — you (or future operators) can review who used recovery and when.
- **`new_password` is returned exactly once** in the HTTP response and is not stored. Capture it before closing the connection.
- **`force_reset=true` is recommended** when handing recovered access to someone else, so they're forced to rotate the password on first login.
