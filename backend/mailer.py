"""
Outgoing email: welcome emails, ID-check updates and password reset codes.

Two ways to send, picked by environment variables:

1. Brevo's HTTP API (use this on Render's free plan, which blocks the SMTP ports 25, 465
   and 587). Make a free account at brevo.com, verify your sender address under
   Senders & IP > Senders, create a key under SMTP & API > API Keys, and set:

       BREVO_API_KEY=xkeysib-...
       MAIL_FROM=Raahi <yourname@gmail.com>     (must be the verified sender)

2. SMTP, e.g. Gmail. Turn on 2-Step Verification for the sending account, create an
   App Password (Google Account > Security > App passwords), and set:

       SMTP_HOST=smtp.gmail.com
       SMTP_PORT=587
       SMTP_USER=yourname@gmail.com
       SMTP_PASSWORD=<the 16-character app password>
       MAIL_FROM=Raahi <yourname@gmail.com>     (optional; defaults to SMTP_USER)

If BREVO_API_KEY is set it is used; otherwise SMTP. With neither, the app still runs: each
email is printed to the server log instead, so password reset can be tried locally
without an email account.

Every email goes out twice in one message: the plain text the code writes, and an HTML
version of the same text under a Raahi header with the logo. The logo is loaded from the
app itself (frontend/icons/icon-192.png), at PUBLIC_URL or, on Render, RENDER_EXTERNAL_URL,
which Render sets on its own. Without either, the header shows the name only.
"""
import html
import json
import os
import re
import smtplib
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

BREVO_URL = "https://api.brevo.com/v3/smtp/email"
DEFAULT_NAME = "Raahi"
LOGO_PATH = "/static/icons/icon-192.png"
TEAL, ORANGE = "#0f4c5c", "#fb923c"          # the logo's colours


class MailError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("BREVO_API_KEY") or os.environ.get("SMTP_HOST"))


def sender() -> tuple[str, str]:
    """(name, address) from MAIL_FROM. Accepts "Raahi <a@b.com>", "Raahi a@b.com" or "a@b.com"."""
    raw = (os.environ.get("MAIL_FROM") or os.environ.get("SMTP_USER") or "").strip()
    name, address = parseaddr(raw)
    if "<" not in raw:                        # no brackets: the address is the word with an @
        found = re.search(r"[^\s<>]+@[^\s<>]+", raw)
        address = found.group(0) if found else ""
        name = raw.replace(address, "").strip()
    return name.strip(' "') or DEFAULT_NAME, address


def logo_url() -> str | None:
    base = (os.environ.get("PUBLIC_URL") or os.environ.get("RENDER_EXTERNAL_URL") or "").strip().rstrip("/")
    return base + LOGO_PATH if base.startswith("https://") else None


def html_body(subject: str, body: str) -> str:
    """The plain-text email laid out as HTML under a Raahi header. Email clients ignore <style>
    blocks unevenly, so every style is inline and the layout is a table."""
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;">{html.escape(part).replace(chr(10), "<br>")}</p>'
        for part in body.strip().split("\n\n"))
    logo = logo_url()
    mark = (f'<img src="{html.escape(logo)}" width="44" height="44" alt="" '
            f'style="display:block;border:0;border-radius:10px;">' if logo else "")
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(subject)}</title></head>
<body style="margin:0;padding:0;background:#f3f5f6;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f5f6;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:560px;background:#ffffff;border-radius:12px;overflow:hidden;">
<tr><td style="background:{TEAL};padding:18px 24px;border-bottom:4px solid {ORANGE};">
<table role="presentation" cellpadding="0" cellspacing="0"><tr>
<td style="padding-right:{12 if logo else 0}px;">{mark}</td>
<td style="font-family:Arial,Helvetica,sans-serif;font-size:24px;font-weight:bold;color:#ffffff;letter-spacing:0.5px;">Raahi</td>
</tr></table></td></tr>
<tr><td style="padding:28px 24px 12px;font-family:Arial,Helvetica,sans-serif;font-size:15px;line-height:1.6;color:#1f2933;">
{paragraphs}</td></tr>
<tr><td style="padding:16px 24px 24px;font-family:Arial,Helvetica,sans-serif;font-size:12px;color:#7b8794;border-top:1px solid #e4e7eb;">
Raahi &middot; Rides across Jammu &amp; Kashmir</td></tr>
</table></td></tr></table>
</body></html>"""


def send(to: str, subject: str, body: str) -> None:
    if os.environ.get("BREVO_API_KEY"):
        _send_brevo(to, subject, body)
    elif os.environ.get("SMTP_HOST"):
        _send_smtp(to, subject, body)
    else:
        print(f"[mail] Neither BREVO_API_KEY nor SMTP_HOST is set, so this email was not sent.\n"
              f"[mail] To: {to}\n[mail] Subject: {subject}\n{body}\n[mail] ---")


def _send_brevo(to: str, subject: str, body: str) -> None:
    name, address = sender()
    if not address:
        print("[mail] BREVO_API_KEY is set but MAIL_FROM is not, so there is no sender address.")
        raise MailError("MAIL_FROM is not set")
    payload = json.dumps({
        "sender": {"name": name, "email": address},
        "to": [{"email": to}],
        "subject": subject,
        "textContent": body,
        "htmlContent": html_body(subject, body),
    }).encode()
    request = urllib.request.Request(BREVO_URL, data=payload, method="POST", headers={
        "api-key": os.environ["BREVO_API_KEY"],
        "content-type": "application/json",
        "accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=20):
            pass
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        print(f"[mail] sending to {to} through Brevo failed: HTTP {e.code} {detail}")
        raise MailError(f"Brevo HTTP {e.code}") from e
    except OSError as e:
        print(f"[mail] sending to {to} through Brevo failed: {e}")
        raise MailError(str(e)) from e


def _send_smtp(to: str, subject: str, body: str) -> None:
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASSWORD", "")
    message = EmailMessage()
    message["From"] = os.environ.get("MAIL_FROM") or user
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)
    message.add_alternative(html_body(subject, body), subtype="html")
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        with server:
            if user:
                server.login(user, password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError) as e:
        print(f"[mail] sending to {to} failed: {e}")
        raise MailError(str(e)) from e


def send_quietly(to: str | None, subject: str, body: str) -> None:
    """For background notices: a failure is logged and dropped, never shown to the user."""
    if not to:
        return
    try:
        send(to, subject, body)
    except MailError:
        pass
