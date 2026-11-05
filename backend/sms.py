"""
Outgoing SMS, for ID check results.

Sent through Twilio when these environment variables are set:

    TWILIO_ACCOUNT_SID=ACxxxxxxxx
    TWILIO_AUTH_TOKEN=<auth token>
    TWILIO_FROM=+1xxxxxxxxxx          (a Twilio number that can send to India)

Without them the app still runs: each SMS is printed to the server log instead, the same
way emails are when SMTP is not set up. Note that commercial SMS to Indian numbers needs
DLT registration of the sender and message templates with an Indian telecom operator.
"""
import os

import httpx


class SmsError(Exception):
    pass


def configured() -> bool:
    return all(os.environ.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"))


def send(phone: str, text: str) -> None:
    """phone: a 10-digit Indian mobile number, as stored on the account."""
    to = f"+91{phone}"
    if not configured():
        print(f"[sms] Twilio is not set up, so this SMS was not sent.\n[sms] To: {to}\n{text}\n[sms] ---")
        return
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    try:
        response = httpx.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json",
                              auth=(sid, os.environ["TWILIO_AUTH_TOKEN"]),
                              data={"From": os.environ["TWILIO_FROM"], "To": to, "Body": text}, timeout=20)
        response.raise_for_status()
    except httpx.HTTPError as e:
        print(f"[sms] sending to {to} failed: {e}")
        raise SmsError(str(e)) from e
