"""
Outgoing email, for password reset codes.

Configured with environment variables. For Gmail, turn on 2-Step Verification for the
sending account, create an App Password (Google Account > Security > App passwords), and set:

    SMTP_HOST=smtp.gmail.com
    SMTP_PORT=587
    SMTP_USER=yourname@gmail.com
    SMTP_PASSWORD=<the 16-character app password>
    MAIL_FROM=Raahi <yourname@gmail.com>     (optional; defaults to SMTP_USER)

Without SMTP_HOST the app still runs: each email is printed to the server log instead, so
password reset can be tried locally without an email account.
"""
import os
import smtplib
from email.message import EmailMessage


class MailError(Exception):
    pass


def configured() -> bool:
    return bool(os.environ.get("SMTP_HOST"))


def send(to: str, subject: str, body: str) -> None:
    if not configured():
        print(f"[mail] SMTP_HOST is not set, so this email was not sent.\n"
              f"[mail] To: {to}\n[mail] Subject: {subject}\n{body}\n[mail] ---")
        return

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
