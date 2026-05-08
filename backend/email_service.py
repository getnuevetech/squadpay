"""
Tiny SMTP email helper used for transactional emails (admin password reset, etc).

Reads config from env (loaded by the calling module via `dotenv`):
- EMAIL_HOST, EMAIL_PORT, EMAIL_USER, EMAIL_PASSWORD
- EMAIL_FROM_NAME (display name on the From: header)

Uses Python's stdlib `smtplib` so no new dependencies are added.
"""

from __future__ import annotations
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Iterable

log = logging.getLogger("email_service")


class EmailNotConfigured(RuntimeError):
    """Raised when EMAIL_* env vars are missing — caller decides how to surface this."""


def _config():
    host = os.environ.get("EMAIL_HOST")
    port = int(os.environ.get("EMAIL_PORT") or 587)
    user = os.environ.get("EMAIL_USER")          # SMTP login (must be a real mailbox)
    password = os.environ.get("EMAIL_PASSWORD")  # App Password
    from_name = os.environ.get("EMAIL_FROM_NAME") or "SquadPay"
    # Optional: send-as alias. Falls back to the SMTP login if not configured.
    from_addr = os.environ.get("EMAIL_FROM") or user
    if not (host and user and password):
        raise EmailNotConfigured(
            "EMAIL_HOST / EMAIL_USER / EMAIL_PASSWORD must be set in backend env"
        )
    # Gmail App Passwords are sometimes pasted with spaces — strip them defensively.
    password = password.replace(" ", "")
    return host, port, user, password, from_name, from_addr


def send_email(
    to: str | Iterable[str],
    subject: str,
    text_body: str,
    html_body: str | None = None,
    reply_to: str | None = None,
) -> None:
    """Send a transactional email via SMTP. Raises on failure so caller can react."""
    host, port, user, password, from_name, from_addr = _config()
    recipients = [to] if isinstance(to, str) else list(to)
    if not recipients:
        raise ValueError("send_email called with no recipients")

    msg = EmailMessage()
    # Show the friendly alias as the From: header. SMTP login still uses `user`
    # (the real Workspace mailbox).
    msg["From"] = formataddr((from_name, from_addr))
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    if reply_to:
        msg["Reply-To"] = reply_to
    # Plain-text body first, HTML alternative on top.
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    log.info("[email] sending to=%s subject=%r host=%s:%s", recipients, subject, host, port)
    ctx = ssl.create_default_context()
    # Gmail recommends STARTTLS on port 587. SMTP_SSL on 465 also works if you ever
    # need to switch — keep this branchless and stick with STARTTLS for now.
    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ctx)
        smtp.ehlo()
        smtp.login(user, password)
        smtp.send_message(msg)
    log.info("[email] sent ok to=%s", recipients)


def render_admin_reset_email(reset_url: str, admin_name: str = "Admin") -> tuple[str, str]:
    """Returns (text_body, html_body) for the admin password reset email."""
    text = (
        f"Hi {admin_name},\n\n"
        "We received a request to reset your SquadPay admin password.\n\n"
        f"Reset your password here (link expires in 30 minutes):\n{reset_url}\n\n"
        "If you didn't request this, you can safely ignore this email — your password will stay unchanged.\n\n"
        "— SquadPay\n"
    )
    html = f"""\
<!doctype html>
<html>
  <body style="margin:0;padding:0;background:#F8FAFC;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;color:#0F172A;">
    <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="padding:32px 16px;">
      <tr><td align="center">
        <table role="presentation" width="520" cellspacing="0" cellpadding="0"
               style="max-width:520px;background:#fff;border-radius:16px;border:1px solid #E5E7EB;overflow:hidden;">
          <tr>
            <td style="background:linear-gradient(135deg,#7C3AED,#4F46E5);padding:32px;text-align:center;">
              <div style="display:inline-block;width:56px;height:56px;background:rgba(255,255,255,.18);border-radius:18px;line-height:56px;font-size:26px;font-weight:800;color:#fff;letter-spacing:-1px;">SP</div>
              <div style="margin-top:12px;font-size:18px;font-weight:700;letter-spacing:0.4px;color:#fff;text-transform:uppercase;">SquadPay&nbsp;Admin</div>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 32px 8px 32px;">
              <h1 style="margin:0 0 12px 0;font-size:22px;font-weight:800;color:#0F172A;">Reset your password</h1>
              <p style="margin:0 0 16px 0;font-size:15px;line-height:22px;color:#4B5563;">
                Hi {admin_name},<br>
                We received a request to reset your SquadPay admin password. Click the button below to set a new one. This link expires in 30 minutes.
              </p>
              <div style="text-align:center;margin:24px 0;">
                <a href="{reset_url}"
                   style="display:inline-block;padding:14px 28px;border-radius:999px;background:linear-gradient(135deg,#7C3AED,#4F46E5);color:#fff;font-weight:700;text-decoration:none;font-size:15px;">
                  Reset password
                </a>
              </div>
              <p style="margin:0 0 8px 0;font-size:13px;color:#6B7280;">Or paste this link into your browser:</p>
              <p style="word-break:break-all;margin:0 0 16px 0;font-size:12px;color:#7C3AED;">
                <a style="color:#7C3AED;text-decoration:none;" href="{reset_url}">{reset_url}</a>
              </p>
              <p style="margin:24px 0 0 0;font-size:13px;color:#6B7280;line-height:18px;">
                If you didn't request this, you can safely ignore this email — your password will stay unchanged.
              </p>
            </td>
          </tr>
          <tr>
            <td style="background:#F8FAFC;padding:18px 32px;border-top:1px solid #E5E7EB;text-align:center;">
              <p style="margin:0;font-size:12px;color:#9CA3AF;">© SquadPay · This is an automated message, please don't reply.</p>
            </td>
          </tr>
        </table>
      </td></tr>
    </table>
  </body>
</html>
"""
    return text, html
