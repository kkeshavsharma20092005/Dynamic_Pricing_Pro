"""
Paying for a finished trip. A demo of the real flow: no money moves.

When a trip ends, the rider's and the driver's apps show a QR code. It is not a UPI code: it
opens Raahi's own payment page (/pay/<secret link>), so scanning it with a phone camera or
Google Lens never starts a real payment. That page confirms a demo payment, both apps move
on at once, and the rider is asked for feedback. A driver can also mark the fare as paid in
cash. A real launch would swap the page for a payment gateway (such as Razorpay) and mark the
ride paid from the gateway's confirmation; the rest of the flow would not change.
"""
import io
import os
import socket
import time
from datetime import datetime
from html import escape
from urllib.parse import urlsplit

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

import appdb
from rides import IST, broadcast_ride, get_ride, hub, ride_for_participant, ride_view, require_driver

router = APIRouter(tags=["payments"])
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def ride_for_link(token: str) -> dict:
    with appdb.connect() as conn:
        row = conn.execute("SELECT id FROM rides WHERE pay_token = ?", (token,)).fetchone()
    ride = get_ride(row["id"]) if row else None
    if ride is None:
        raise HTTPException(404, "This payment link is not valid.")
    return ride


def lan_address() -> str | None:
    """This computer's address on the local network, so a phone on the same Wi-Fi can open it."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))     # picks the outgoing interface; sends nothing
            return s.getsockname()[0]
    except OSError:
        return None


def public_base(request: Request) -> str:
    """
    The address a phone should open. PUBLIC_URL wins when set. On localhost, a phone cannot
    reach "127.0.0.1" (that is the phone itself), so the computer's network address is used.
    """
    configured = os.environ.get("PUBLIC_URL", "").strip().rstrip("/")
    if configured:
        return configured
    parts = urlsplit(str(request.base_url))
    scheme = request.headers.get("x-forwarded-proto", parts.scheme)   # Render ends HTTPS before the app
    host = parts.hostname
    if host in LOCAL_HOSTS:
        host = lan_address() or host
    port = f":{parts.port}" if parts.port and scheme == parts.scheme else ""
    return f"{scheme}://{host}{port}"


@router.get("/pay/{token}/qr.svg", include_in_schema=False)
def pay_qr(token: str, request: Request):
    ride_for_link(token)
    url = f"{public_base(request)}/pay/{token}"
    image = qrcode.make(url, image_factory=qrcode.image.svg.SvgPathImage, box_size=10, border=2)
    out = io.BytesIO()
    image.save(out)
    return Response(out.getvalue(), media_type="image/svg+xml", headers={"Cache-Control": "no-store"})


def summary(ride: dict) -> dict:
    view = ride_view(ride, {"id": None, "role": "rider"})
    return {"ride_id": ride["id"], "fare": ride["fare"], "status": ride["status"],
            "pickup": ride["pickup"]["name"], "dropoff": ride["dropoff"]["name"],
            "vehicle": ride["quote"]["label"], "driver": view["driver"]["name"] if view["driver"] else None,
            "paid": ride.get("paid_at") is not None, "paid_at": ride.get("paid_at"),
            "method": ride.get("payment_method"), "demo": True}


@router.get("/api/pay/{token}")
def payment_details(token: str):
    return summary(ride_for_link(token))


async def mark_paid(ride: dict, method: str) -> dict:
    """Record the payment once and tell both apps, so they move on to the next step."""
    with appdb.connect() as conn:
        changed = conn.execute(
            "UPDATE rides SET paid_at = ?, payment_method = ?, updated_at = ? "
            "WHERE id = ? AND status = 'completed' AND paid_at IS NULL",
            (time.time(), method, time.time(), ride["id"])).rowcount
    ride = get_ride(ride["id"])
    if changed:
        await broadcast_ride(ride)
        rider = appdb.get_user(ride["rider_id"])
        await hub.send(rider["id"], {"type": "paid", "ride": ride_view(ride, rider)})
    return ride


@router.post("/api/pay/{token}")
async def pay(token: str):
    """What the payment page calls. Paying twice is harmless: the second time just says paid."""
    ride = ride_for_link(token)
    if ride["status"] == "cancelled":
        raise HTTPException(409, "This ride was cancelled, so there is nothing to pay.")
    if ride["status"] != "completed":
        raise HTTPException(409, "You can pay once the trip has ended.")
    return summary(await mark_paid(ride, "qr_demo"))


@router.post("/api/rides/{ride_id}/cash")
async def cash_received(ride_id: int, user: dict = Depends(require_driver)):
    ride = ride_for_participant(ride_id, user)
    if ride["driver_id"] != user["id"]:
        raise HTTPException(403, "Only this ride's driver can mark it paid.")
    if ride["status"] != "completed":
        raise HTTPException(409, "Mark the fare as paid after the trip has ended.")
    return ride_view(await mark_paid(ride, "cash"), user)


# ---------------------------------------------------------------- the page the QR opens
# Built on the server and confirmed with a plain form POST, not a script's fetch(): the
# browsers that open a scanned link (Google Lens, the Google app, camera apps) are often
# in-app viewers that load a page but block or drop its background requests. A form POST
# is an ordinary page load, so it works in all of them, and even with scripts turned off.
PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="theme-color" content="#ffffff" />
  <meta name="robots" content="noindex" />
  <title>Raahi - {title}</title>
  <link rel="icon" href="/static/icons/icon-192.png" />
  <link rel="stylesheet" href="/static/app.css?v=35" />
</head>
<body class="pay-page">
  <header class="topbar"><h1><a href="/">Raahi</a></h1></header>
  <main class="pay-main">
    <section class="confirm-card pay-sheet" aria-live="polite">
      <div class="demo-ribbon">DEMO PAYMENT &middot; NO REAL MONEY IS CHARGED</div>
      {body}
    </section>
  </main>
</body>
</html>"""


def _facts(d: dict) -> str:
    cells = [("Amount", f"&#8377;{d['fare']:,}"), ("Ride", f"#{d['ride_id']}"), ("Vehicle", escape(d["vehicle"]))]
    facts = "".join(f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in cells)
    return (f'<dl class="confirm-facts">{facts}</dl>'
            f'<ol class="confirm-trip"><li class="from"><span class="muted">Pickup</span><strong>{escape(d["pickup"])}</strong></li>'
            f'<li class="to"><span class="muted">Drop-off</span><strong>{escape(d["dropoff"])}</strong></li></ol>')


def _page(title: str, body: str, status: int = 200) -> HTMLResponse:
    return HTMLResponse(PAGE.format(title=escape(title), body=body), status_code=status,
                        headers={"Cache-Control": "no-store"})


def _problem(message: str, status: int, retry: str | None = None) -> HTMLResponse:
    again = f'<a class="cta light" href="{retry}">Try again</a>' if retry else ""
    return _page("Payment not done", f'<div class="confirm-head"><div class="confirm-check pay-fail" aria-hidden="true">!</div>'
                                     f'<h2>Payment not done</h2><p>{escape(message)}</p></div>{again}', status)


@router.get("/pay/{token}", include_in_schema=False)
def pay_page(token: str):
    try:
        ride = ride_for_link(token)
    except HTTPException as error:
        return _problem(error.detail, error.status_code)
    d = summary(ride)
    if d["paid"]:
        when = datetime.fromtimestamp(d["paid_at"], IST).strftime("%d %b %Y, %I:%M %p")
        how = " in cash" if d["method"] == "cash" else ""
        with_driver = f" for your ride with {escape(d['driver'])}" if d["driver"] else ""
        return _page("Payment received",
                     f'<div class="confirm-head"><div class="confirm-check" aria-hidden="true">&#10003;</div>'
                     f'<h2>Payment received</h2><p>&#8377;{d["fare"]:,} paid{with_driver}{how}.</p></div>{_facts(d)}'
                     f'<p class="muted confirm-note">Paid on {when}.</p>'
                     f'<p class="confirm-note">You can close this page. Your Raahi app has moved on to the next step.</p>')
    if ride["status"] == "cancelled":
        return _problem("This ride was cancelled, so there is nothing to pay.", 409)
    if ride["status"] != "completed":
        return _problem("You can pay once the trip has ended.", 409, retry=f"/pay/{token}")
    # Confirms by itself after a moment; the button does the same if scripts are blocked.
    return _page("Pay for your ride",
                 f'<div class="confirm-head"><div class="pay-spinner" aria-hidden="true"></div>'
                 f'<h2>Paying &#8377;{d["fare"]:,}&hellip;</h2><p>Confirming your demo payment with Raahi</p></div>{_facts(d)}'
                 f'<form id="pay-form" method="post" action="/pay/{token}">'
                 f'<button type="submit" class="confirm-done">Pay &#8377;{d["fare"]:,}</button></form>'
                 '<script>setTimeout(function () { var f = document.getElementById("pay-form");'
                 ' f.querySelector("button").disabled = true; f.submit(); }, 1200);</script>')


@router.post("/pay/{token}", include_in_schema=False)
async def pay_page_submit(token: str):
    try:
        ride = ride_for_link(token)
    except HTTPException as error:
        return _problem(error.detail, error.status_code)
    if ride["status"] == "cancelled":
        return _problem("This ride was cancelled, so there is nothing to pay.", 409)
    if ride["status"] != "completed":
        return _problem("You can pay once the trip has ended.", 409, retry=f"/pay/{token}")
    await mark_paid(ride, "qr_demo")
    # Back to the page as a GET, so refreshing the receipt never sends the payment again.
    return RedirectResponse(f"/pay/{token}", status_code=303)
