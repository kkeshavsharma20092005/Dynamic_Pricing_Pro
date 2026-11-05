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
from urllib.parse import urlsplit

import qrcode
import qrcode.image.svg
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

import appdb
from rides import broadcast_ride, get_ride, hub, ride_for_participant, ride_view, require_driver

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
