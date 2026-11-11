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
"""
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
