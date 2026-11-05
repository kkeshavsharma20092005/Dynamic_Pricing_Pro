"""
The ride app: accounts, quotes, booking, dispatch, live tracking, chat and admin.

Dispatch offers the ride to every real online driver first, nearest first, one at a time.
Only when no real driver is online, or every one of them declined or let the offer run out,
does a simulated driver take the ride, so a demo always completes. Simulated trips run at demo speed
(under a minute) whatever the distance. Everything is marked so the UI can say which
parts are simulated.
"""
import asyncio
import hashlib
import json
import os
import random
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

import appdb
import business
import chatbot
import geocode
import localities
import mailer
import placesdb
from config import OUTPUT_DIR, REGIONS
from fares import (DEFAULT_RIVAL_RATES, VEHICLES, available_vehicles, default_conditions,
                   price_option)
from places import BY_NAME, distance_km, in_service_area, nearest_place, plan_route

SECRET = os.environ.get("APP_SECRET") or secrets.token_hex(32)
TOKEN_DAYS = 7
IST = timezone(timedelta(hours=5, minutes=30))
DEFAULT_CAPS = {"normal": 1.3, "hardship": 1.15}
FRONTEND_PHOTOS = OUTPUT_DIR.parent / "frontend" / "photos"
MIN_TRIP_KM = 0.3
# A real driver sees a ride request for up to a minute. The rider never waits longer than
# that for real drivers in total: when the minute is up, the simulated driver takes the ride.
OFFER_SECONDS = int(os.environ.get("OFFER_SECONDS", "60"))
REAL_SEARCH_SECONDS = int(os.environ.get("REAL_SEARCH_SECONDS", "60"))
# With no real driver free, how long to wait (for one to come online) before the
# simulated driver takes the ride. Each real driver's offer restarts this wait.
NO_DRIVER_WAIT_SECONDS = float(os.environ.get("NO_DRIVER_WAIT_SECONDS", "2"))
REAL_DRIVER_RADIUS_KM = 30.0
ROAD_FACTOR = 1.3          # roads are longer than the straight line between two points
CITY_KMPH = 22             # typical in-town speed, for the driver's time to the pickup
SIM_NAMES = ["Rakesh Sharma", "Mohd Yousuf", "Bilal Ahmad", "Sunil Kumar", "Imran Lone",
             "Vikram Singh", "Tariq Mir", "Ajay Gupta", "Farooq Dar", "Ramesh Thakur"]
# Women Raahi rides go only to women drivers, simulated ones included.
SIM_WOMEN_NAMES = ["Priya Sharma", "Shazia Bhat", "Anjali Gupta", "Rubina Akhtar", "Neha Raina",
                   "Saima Mir", "Pooja Thakur", "Nusrat Jan"]
GENDERS = ("female", "male", "other", "unspecified")
SIM_REPLIES = ["Ji, main aa raha hoon.", "2-3 minute mein pahunch raha hoon.",
               "Theek hai, pickup point par rukiye.", "Okay, noted."]
ACTIVE = ("searching", "accepted", "arrived", "in_progress")

router = APIRouter(prefix="/api", tags=["rides"])


class Hub:
    """Live connections and the state that only matters while the server is up."""

    def __init__(self):
        self.engine = None
        self.sockets: dict[int, set[WebSocket]] = {}
        self.admins: set[int] = set()
        self.drivers: dict[int, dict] = {}       # online real drivers
        self.offers: dict[int, dict] = {}        # ride id -> {"event", "driver"}
        self.tasks: dict[int, asyncio.Task] = {}
        self.chats: dict[int, dict] = {}         # user id -> assistant conversation

    async def send(self, user_id, event: dict):
        for ws in list(self.sockets.get(user_id, ())):
            try:
                await ws.send_json(event)
            except (RuntimeError, WebSocketDisconnect):
                self.sockets[user_id].discard(ws)

    async def to_ride(self, ride: dict, event: dict):
        recipients = {ride["rider_id"], *self.admins}
        if ride["driver_id"]:
            recipients.add(ride["driver_id"])
        for user_id in recipients:
            await self.send(user_id, event)


hub = Hub()


# ------------------------------------------------------------------ accounts
class RegisterBody(BaseModel):
    phone: str
    name: str = Field(..., min_length=2, max_length=60)
    password: str = Field(..., min_length=8, max_length=128)
    email: str = Field(..., max_length=254)
    role: str = "rider"
    vehicle: str | None = None


class LoginBody(BaseModel):
    phone: str
    password: str
    role: str = "rider"


class ForgotBody(BaseModel):
    phone: str
    role: str = "rider"


class ResetBody(BaseModel):
    phone: str
    role: str = "rider"
    code: str = Field(..., max_length=12)
    password: str = Field(..., min_length=8, max_length=128)


EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
RESET_MINUTES = 15
RESET_MAX_ATTEMPTS = 5
RESET_RESEND_SECONDS = 60


def password_version(user: dict) -> str:
    # Changes whenever the password does, so a reset signs out every older session.
    return hashlib.sha256(user["password_hash"].encode()).hexdigest()[:16]


def make_token(user: dict) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS)
    return jwt.encode({"sub": str(user["id"]), "pv": password_version(user), "exp": expires},
                      SECRET, algorithm="HS256")


def user_from_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    user = appdb.get_user(int(payload["sub"]))
    if user is None or payload.get("pv") != password_version(user):
        return None
    return user


def current_user(authorization: str = Header(default="")) -> dict:
    user = user_from_token(authorization.removeprefix("Bearer "))
    if user is None:
        raise HTTPException(401, "Please log in again.")
    return user


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "admin":
        raise HTTPException(403, "Admin only.")
    return user


def public_user(user: dict) -> dict:
    view = {k: user.get(k) for k in ("id", "phone", "name", "role", "vehicle", "email", "gender", "kyc", "kyc_note")}
    view["plate"] = show_plate(user.get("plate"))
    return view


def show_plate(plate):
    """JK02AB1234 -> JK02 AB 1234, the way it is painted on the plate."""
    match = re.fullmatch(r"([A-Z]{2}\d{1,2})([A-Z]{0,3})(\d{4})", plate or "")
    return " ".join(part for part in match.groups() if part) if match else plate


@router.post("/register")
def register(body: RegisterBody):
    if not re.fullmatch(r"[6-9]\d{9}", body.phone):
        raise HTTPException(422, "Enter a valid 10-digit mobile number.")
    if body.role not in ("rider", "driver"):
        raise HTTPException(422, "Role must be rider or driver.")
    if body.role == "driver" and body.vehicle not in VEHICLES:
        raise HTTPException(422, "Choose a vehicle type.")
    email = body.email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        raise HTTPException(422, "Enter a valid email address.")
    try:
        user_id = appdb.create_user(body.phone, body.name.strip(), body.role, body.password,
                                    body.vehicle if body.role == "driver" else None, email)
    except appdb.IntegrityError:
        raise HTTPException(409, f"This number already has a {body.role} account.")
    # No session here: a new account logs in with its credentials like any other.
    return {"user": public_user(appdb.get_user(user_id)),
            "message": "Account created. Log in with your mobile number and password."}


@router.post("/login")
def login(body: LoginBody):
    user = appdb.verify_user(body.phone, body.password, body.role)
    if user is None:
        raise HTTPException(401, f"No {body.role} account matches that number and password.")
    return {"token": make_token(user), "user": public_user(user)}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)


class GenderBody(BaseModel):
    gender: str


@router.post("/me/gender")
def set_gender(body: GenderBody, user: dict = Depends(current_user)):
    """
    Asked once, after the first login. Only women drivers get Women Raahi rides, so it
    cannot be switched here afterwards: a change goes through Raahi support.
    """
    if user["role"] == "admin":
        raise HTTPException(403, "Admin accounts have no gender setting.")
    if body.gender not in GENDERS:
        raise HTTPException(422, "Choose one of the options.")
    if not appdb.set_gender_once(user["id"], body.gender):
        raise HTTPException(409, "Your gender is already saved. Contact Raahi support to change it.")
    return public_user(appdb.get_user(user["id"]))


# The answer is the same whether or not the number has an account, so this cannot be used
# to find out who is registered.
RESET_SENT = ("If this number has an account with an email address, we have emailed it a "
              f"6-digit code. The code works for {RESET_MINUTES} minutes.")


@router.post("/password/forgot")
def forgot_password(body: ForgotBody):
    user = appdb.find_user(body.phone, body.role)
    if user is None or not user.get("email") or user["role"] == "admin":
        return {"message": RESET_SENT}
    previous = appdb.get_reset(user["id"])
    if previous and time.time() - previous["sent_at"] < RESET_RESEND_SECONDS:
        return {"message": RESET_SENT}
    code = f"{secrets.randbelow(10 ** 6):06d}"
    appdb.save_reset_code(user["id"], code, time.time() + RESET_MINUTES * 60)
    try:
        mailer.send(user["email"], "Your Raahi password reset code",
                    f"Hello {user['name']},\n\n"
                    f"Your code to reset your Raahi {user['role']} password is: {code}\n\n"
                    f"It works for {RESET_MINUTES} minutes. If you did not ask for this, ignore "
                    f"this email: your password stays the same.\n\nRaahi")
    except mailer.MailError:
        appdb.delete_reset(user["id"])
        raise HTTPException(503, "We could not send the email right now. Please try again in a few minutes.")
    return {"message": RESET_SENT}


@router.post("/password/reset")
def reset_password(body: ResetBody):
    invalid = HTTPException(400, "That code is wrong or has expired. Ask for a new code.")
    user = appdb.find_user(body.phone, body.role)
    reset = appdb.get_reset(user["id"]) if user else None
    if reset is None or time.time() > reset["expires_at"] or reset["attempts"] >= RESET_MAX_ATTEMPTS:
        raise invalid
    if not appdb.reset_code_matches(reset, body.code.strip()):
        appdb.count_reset_attempt(user["id"])
        raise invalid
    appdb.set_password(user["id"], body.password)
    appdb.delete_reset(user["id"])
    return {"message": "Password changed. Log in with your new password."}


# ------------------------------------------------------------------ conditions
def now_ist() -> datetime:
    return datetime.now(IST)


def conditions_for(region: str) -> dict:
    saved = appdb.get_setting(f"conditions:{region}")
    return saved or default_conditions(region, now_ist().month)


def fair_caps() -> dict:
    return appdb.get_setting("fair_caps", DEFAULT_CAPS)


def rival_rates() -> dict:
    return appdb.get_setting("rival_rates", DEFAULT_RIVAL_RATES)


# ------------------------------------------------------------------ quotes
class Point(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lon: float = Field(..., ge=-180, le=180)
    name: str | None = Field(None, max_length=120)


class QuoteBody(BaseModel):
    pickup: Point
    dropoff: Point


def build_quote(body: QuoteBody) -> dict:
    for label, point in (("Pickup", body.pickup), ("Drop-off", body.dropoff)):
        if not in_service_area(point.lat, point.lon):
            raise HTTPException(422, f"{label} is outside the Jammu & Kashmir service area.")

    route = plan_route(body.pickup.lat, body.pickup.lon, body.dropoff.lat, body.dropoff.lon)
    if route["km"] < MIN_TRIP_KM:
        raise HTTPException(422, "Pickup and drop-off are too close together.")

    crosses = route["start_region"] != route["end_region"]
    if crosses:
        closed = [r for r in route["regions"] if conditions_for(r)["road_closed"]]
        if closed:
            names = ", ".join(REGIONS[r]["name"] for r in closed)
            raise HTTPException(409, f"Road closed through {names}. This trip cannot be booked right now.")

    region = route["start_region"]
    conditions = conditions_for(region)
    vehicles = available_vehicles(region, route["km"], crosses)
    if not vehicles:
        raise HTTPException(422, "No vehicle type serves this trip.")

    when, caps, rates = now_ist(), fair_caps(), rival_rates()
    options = [price_option(hub.engine, v, region, route["km"], when, conditions, caps, rates)
               for v in vehicles]
    return {
        "pickup": label_point(body.pickup), "dropoff": label_point(body.dropoff),
        "km": route["km"], "minutes": route["minutes"], "path": route["path"], "routed": route["routed"],
        "region": region, "region_name": REGIONS[region]["name"],
        "weather": conditions["weather_condition"], "road_closed": conditions["road_closed"],
        "options": options,
    }


def label_point(point: Point) -> dict:
    return {"lat": point.lat, "lon": point.lon,
            "name": point.name or f"Near {nearest_place(point.lat, point.lon)['name']}"}


@router.get("/places")
def places():
    return sorted(BY_NAME.values(), key=lambda p: p["name"])


@router.post("/quote")
def quote(body: QuoteBody, user: dict = Depends(current_user)):
    return build_quote(body)


@router.get("/nearby")
def nearby(lat: float, lon: float, user: dict = Depends(current_user)):
    """Demo markers near a point: real online drivers plus a stable simulated few."""
    rng = random.Random(f"{round(lat, 2)}:{round(lon, 2)}")
    simulated = [{"lat": lat + rng.uniform(-.018, .018), "lon": lon + rng.uniform(-.018, .018),
                  "simulated": True} for _ in range(5)]
    real = [{"lat": d["lat"], "lon": d["lon"], "simulated": False}
            for d in hub.drivers.values()
            if distance_km(lat, lon, d["lat"], d["lon"]) <= REAL_DRIVER_RADIUS_KM]
    return real + simulated


# ------------------------------------------------------------------ rides
class BookBody(QuoteBody):
    vehicle: str
    women_only: bool = False


def check_women_only(user: dict, women_only: bool):
    if not women_only:
        return
    if user.get("gender") != "female":
        raise HTTPException(403, "Women Raahi rides are for women riders.")
    if user.get("kyc") != "approved":
        raise HTTPException(403, "Verify your ID once to use Women Raahi.")


def row_to_ride(row) -> dict:
    ride = dict(row)
    for key in ("pickup", "dropoff", "quote", "path"):
        ride[key] = json.loads(ride[key])
    ride["sim_driver"] = json.loads(ride["sim_driver"]) if ride["sim_driver"] else None
    ride["women_only"] = bool(ride.get("women_only"))
    return ride


def get_ride(ride_id: int) -> dict | None:
    with appdb.connect() as conn:
        row = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    return row_to_ride(row) if row else None


def ride_view(ride: dict, viewer: dict) -> dict:
    """What this viewer may see. Phone numbers are shared only while a ride is live."""
    view = {k: ride[k] for k in ride if k not in ("rider_id", "driver_id")}
    if viewer["role"] != "admin":
        # The commission and cost split is business data, for the admin only.
        view["quote"] = {k: v for k, v in ride["quote"].items() if k != "business"}
    live = ride["status"] in ("accepted", "arrived", "in_progress")
    vehicle = VEHICLES[ride["vehicle"]]["label"]
    if ride["sim_driver"]:
        view["driver"] = {"name": ride["sim_driver"]["name"], "simulated": True, "phone": None,
                          "plate": ride["sim_driver"].get("plate"), "vehicle": vehicle,
                          "to_pickup": to_pickup(ride, ride["sim_driver"]["start"])}
    elif ride["driver_id"]:
        driver = appdb.get_user(ride["driver_id"])
        online = hub.drivers.get(ride["driver_id"])
        view["driver"] = {"name": driver["name"], "simulated": False, "plate": show_plate(driver.get("plate")),
                          "phone": driver["phone"] if live else None, "vehicle": vehicle,
                          "to_pickup": to_pickup(ride, (online["lat"], online["lon"])) if online else None}
    else:
        view["driver"] = None
    if ride["status"] != "accepted" and view["driver"]:
        view["driver"]["to_pickup"] = None     # only meaningful while the driver is on the way
    view["feedback"] = feedback_for(ride["id"]) if ride["status"] == "completed" else None
    if viewer["role"] == "driver" or viewer["role"] == "admin":
        rider = appdb.get_user(ride["rider_id"])
        view["rider"] = {"name": rider["name"], "phone": rider["phone"] if live else None}
    return view


def to_pickup(ride: dict, start) -> dict:
    """Roughly how far the driver is from the pickup, by road, and how long that takes."""
    km = round(distance_km(start[0], start[1], ride["pickup"]["lat"], ride["pickup"]["lon"]) * ROAD_FACTOR, 1)
    return {"km": km, "minutes": max(1, round(km / CITY_KMPH * 60))}


def set_status(ride_id: int, status: str, expected: tuple, **fields) -> dict | None:
    """Move a ride only from an expected status, so two actors cannot both win a race."""
    columns = ", ".join(f"{k} = ?" for k in fields)
    sql = f"UPDATE rides SET status = ?, updated_at = ?{', ' + columns if columns else ''} " \
          f"WHERE id = ? AND status IN ({', '.join('?' * len(expected))})"
    with appdb.connect() as conn:
        changed = conn.execute(sql, (status, time.time(), *fields.values(), ride_id, *expected)).rowcount
    return get_ride(ride_id) if changed else None


async def broadcast_ride(ride: dict):
    recipients = {ride["rider_id"], *hub.admins}
    if ride["driver_id"]:
        recipients.add(ride["driver_id"])
    for user_id in recipients:
        viewer = appdb.get_user(user_id)
        await hub.send(user_id, {"type": "ride", "ride": ride_view(ride, viewer)})


async def announce_driver(ride: dict):
    """Tell the rider, once, that a driver has taken their ride: the app shows a pop-up."""
    rider = appdb.get_user(ride["rider_id"])
    await hub.send(rider["id"], {"type": "confirmed", "ride": ride_view(ride, rider)})


def active_ride_for(user: dict) -> dict | None:
    column = "driver_id" if user["role"] == "driver" else "rider_id"
    with appdb.connect() as conn:
        row = conn.execute(
            f"SELECT * FROM rides WHERE {column} = ? AND status IN ({', '.join('?' * len(ACTIVE))}) "
            "ORDER BY id DESC LIMIT 1", (user["id"], *ACTIVE)).fetchone()
    return row_to_ride(row) if row else None


@router.post("/rides")
async def book(body: BookBody, user: dict = Depends(current_user)):
    if user["role"] != "rider":
        raise HTTPException(403, "Only rider accounts can book.")
    if active_ride_for(user):
        raise HTTPException(409, "You already have an active ride.")
    check_women_only(user, body.women_only)

    # Re-priced here: a client-supplied fare must never be trusted.
    quoted = build_quote(body)
    option = next((o for o in quoted["options"] if o["vehicle"] == body.vehicle), None)
    if option is None:
        raise HTTPException(422, "That vehicle is not available for this trip.")
    ride = await create_ride(user, quoted, option, body.women_only)
    return ride_view(ride, user)


async def create_ride(user: dict, quoted: dict, option: dict, women_only: bool = False) -> dict:
    now = time.time()
    # Saved with the ride, so later edits to the assumptions never rewrite its economics.
    option = {**option, "business": business_assumptions()}
    with appdb.connect() as conn:
        ride_id = conn.execute(
            "INSERT INTO rides (rider_id, women_only, status, pickup, dropoff, vehicle, region, km, minutes, "
            "fare, quote, path, created_at, updated_at) VALUES (?, ?, 'searching', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user["id"], int(women_only), json.dumps(quoted["pickup"]), json.dumps(quoted["dropoff"]), option["vehicle"],
             quoted["region"], quoted["km"], quoted["minutes"], option["fare"], json.dumps(option),
             json.dumps(quoted["path"]), now, now)).lastrowid

    ride = get_ride(ride_id)
    hub.tasks[ride_id] = asyncio.create_task(dispatch(ride_id))
    await broadcast_ride(ride)
    return ride


@router.get("/rides")
def my_rides(user: dict = Depends(current_user)):
    column = "driver_id" if user["role"] == "driver" else "rider_id"
    with appdb.connect() as conn:
        rows = conn.execute(f"SELECT * FROM rides WHERE {column} = ? ORDER BY id DESC LIMIT 50",
                            (user["id"],)).fetchall()
    return [ride_view(row_to_ride(r), user) for r in rows]


@router.get("/rides/active")
def active(user: dict = Depends(current_user)):
    ride = active_ride_for(user)
    return ride_view(ride, user) if ride else None


def ride_for_participant(ride_id: int, user: dict) -> dict:
    ride = get_ride(ride_id)
    allowed = ride and (user["role"] == "admin" or user["id"] in (ride["rider_id"], ride["driver_id"]))
    if not allowed:
        raise HTTPException(404, "Ride not found.")
    return ride


@router.post("/rides/{ride_id}/cancel")
async def cancel(ride_id: int, user: dict = Depends(current_user)):
    ride = ride_for_participant(ride_id, user)
    updated = set_status(ride_id, "cancelled", ("searching", "accepted", "arrived"))
    if updated is None:
        raise HTTPException(409, f"A ride that is {ride['status']} cannot be cancelled.")
    release_driver(ride["driver_id"])
    await broadcast_ride(updated)
    return ride_view(updated, user)


def release_driver(driver_id):
    if driver_id in hub.drivers:
        hub.drivers[driver_id]["busy"] = False


# ------------------------------------------------------------------ dispatch
def next_candidate(ride: dict, tried: set) -> dict | None:
    """The nearest free online driver who can take this ride and hasn't seen it yet."""
    pickup = ride["pickup"]
    holding_offer = {o["driver"] for o in hub.offers.values()}   # one offer at a time per driver
    near = [d for d in hub.drivers.values()
            if not d["busy"] and d["vehicle"] == ride["vehicle"]
            and (not ride["women_only"] or d["gender"] == "female")    # Women Raahi: women drivers only
            and d["id"] not in tried and d["id"] not in holding_offer
            and distance_km(pickup["lat"], pickup["lon"], d["lat"], d["lon"]) <= REAL_DRIVER_RADIUS_KM]
    return min(near, key=lambda d: distance_km(pickup["lat"], pickup["lon"], d["lat"], d["lon"]), default=None)


async def offer_to(ride: dict, driver: dict, seconds: float) -> None:
    """Show the ride to one driver and wait until they answer or the offer runs out."""
    ride_id = ride["id"]
    event = asyncio.Event()
    hub.offers[ride_id] = {"event": event, "driver": driver["id"]}
    await hub.send(driver["id"], {"type": "offer", "ride": ride_view(ride, appdb.get_user(driver["id"])),
                                  "to_pickup": to_pickup(ride, (driver["lat"], driver["lon"])),
                                  "seconds": round(seconds)})
    try:
        await asyncio.wait_for(event.wait(), seconds)
    except asyncio.TimeoutError:
        await hub.send(driver["id"], {"type": "offer_gone", "ride_id": ride_id})
    finally:
        hub.offers.pop(ride_id, None)


async def dispatch(ride_id: int):
    # Real drivers always come first: the simulated driver is used only once no free, online
    # driver with the right vehicle is left to ask. Drivers are looked up again before each
    # offer, so one who goes online (or finishes a trip) meanwhile is asked too.
    tried = set()
    deadline = time.monotonic() + NO_DRIVER_WAIT_SECONDS
    search_ends = time.monotonic() + REAL_SEARCH_SECONDS
    while time.monotonic() < min(deadline, search_ends):
        ride = get_ride(ride_id)
        if ride is None or ride["status"] != "searching":
            return    # accepted by a real driver, or cancelled
        driver = next_candidate(ride, tried)
        if driver is None:
            await asyncio.sleep(0.25)
            continue
        tried.add(driver["id"])
        # A driver asked late in the minute gets only what is left of it.
        left = search_ends - time.monotonic()
        if left < 1:
            break
        await offer_to(ride, driver, min(OFFER_SECONDS, left))
        deadline = time.monotonic() + NO_DRIVER_WAIT_SECONDS

    ride = get_ride(ride_id)
    if ride and ride["status"] == "searching":
        await run_simulated_trip(ride_id)


def point_along(path: list, fraction: float) -> tuple:
    legs = [distance_km(*a, *b) for a, b in zip(path, path[1:])]
    remaining = sum(legs) * min(max(fraction, 0.0), 1.0)
    for (a, b), leg in zip(zip(path, path[1:]), legs):
        if remaining <= leg and leg > 0:
            t = remaining / leg
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        remaining -= leg
    return tuple(path[-1])


async def drive(ride: dict, path: list, seconds: int, while_status: str) -> bool:
    """Move the simulated driver along a path. False if the ride changed meanwhile."""
    for tick in range(1, seconds + 1):
        await asyncio.sleep(1)
        if get_ride(ride["id"])["status"] != while_status:
            return False
        lat, lon = point_along(path, tick / seconds)
        await hub.to_ride(ride, {"type": "position", "ride_id": ride["id"], "lat": lat, "lon": lon,
                                 "progress": tick / seconds})
    return True


async def run_simulated_trip(ride_id: int):
    ride = get_ride(ride_id)
    rng = random.Random(ride_id)
    pickup = (ride["pickup"]["lat"], ride["pickup"]["lon"])
    start = (pickup[0] + rng.uniform(-.015, .015), pickup[1] + rng.uniform(-.015, .015))
    # A J&K-style plate, so the demo ride card looks like a real one.
    plate = (f"{rng.choice(['JK01', 'JK02', 'JK21'])} {rng.choice('ABCDEFGHJKLMNPRSTUVWXYZ')}"
             f"{rng.choice('ABCDEFGHJKLMNPRSTUVWXYZ')} {rng.randint(1000, 9999)}")
    sim_driver = {"name": rng.choice(SIM_WOMEN_NAMES if ride["women_only"] else SIM_NAMES), "start": start,
                  "plate": plate}

    ride = set_status(ride_id, "accepted", ("searching",), sim_driver=json.dumps(sim_driver))
    if ride is None:
        return
    await broadcast_ride(ride)
    await announce_driver(ride)
    if not await drive(ride, [start, pickup], 10, "accepted"):
        return

    ride = set_status(ride_id, "arrived", ("accepted",))
    if ride is None:
        return
    await broadcast_ride(ride)
    await asyncio.sleep(4)

    ride = set_status(ride_id, "in_progress", ("arrived",))
    if ride is None:
        return
    await broadcast_ride(ride)
    trip_seconds = min(40, max(15, int(ride["km"])))
    if not await drive(ride, ride["path"], trip_seconds, "in_progress"):
        return

    ride = set_status(ride_id, "completed", ("in_progress",))
    if ride:
        await broadcast_ride(ride)


# ------------------------------------------------------------------ real drivers
class DriverState(BaseModel):
    online: bool
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)


def require_driver(user: dict = Depends(current_user)) -> dict:
    if user["role"] != "driver":
        raise HTTPException(403, "Driver accounts only.")
    return user


@router.post("/driver/state")
async def driver_state(body: DriverState, user: dict = Depends(require_driver)):
    if not body.online:
        hub.drivers.pop(user["id"], None)
        return {"online": False}
    if user.get("kyc") != "approved":
        # Every driver's ID and licence are checked before their first ride.
        raise HTTPException(403, "Your documents must be approved before you can go online.")
    if body.lat is None or body.lon is None:
        raise HTTPException(422, "Location is needed to go online.")
    if not in_service_area(body.lat, body.lon):
        raise HTTPException(422, "You are outside the Jammu & Kashmir service area.")
    ride = active_ride_for(user)
    hub.drivers[user["id"]] = {"id": user["id"], "vehicle": user["vehicle"], "gender": user.get("gender"), "lat": body.lat,
                               "lon": body.lon, "busy": ride is not None}
    if ride:
        await hub.to_ride(ride, {"type": "position", "ride_id": ride["id"], "lat": body.lat, "lon": body.lon})
    return {"online": True}


def offer_for(ride_id: int, user: dict) -> dict:
    offer = hub.offers.get(ride_id)
    if offer is None or offer["driver"] != user["id"]:
        raise HTTPException(409, "This offer has expired.")
    return offer


@router.post("/rides/{ride_id}/accept")
async def accept(ride_id: int, user: dict = Depends(require_driver)):
    # Offers only reach approved drivers, who are the only ones allowed online. This is a
    # second lock, so no path lets an unchecked driver take a rider.
    if user.get("kyc") != "approved":
        raise HTTPException(403, "Your documents must be approved before you can accept rides.")
    offer = offer_for(ride_id, user)
    ride = set_status(ride_id, "accepted", ("searching",), driver_id=user["id"])
    if ride is None:
        raise HTTPException(409, "This ride is no longer available.")
    if user["id"] in hub.drivers:
        hub.drivers[user["id"]]["busy"] = True
    offer["event"].set()
    await broadcast_ride(ride)
    await announce_driver(ride)
    return ride_view(ride, user)


@router.post("/rides/{ride_id}/decline")
async def decline(ride_id: int, user: dict = Depends(require_driver)):
    offer_for(ride_id, user)["event"].set()
    return {"ok": True}


DRIVER_STEPS = {"arrived": ("accepted",), "in_progress": ("arrived",), "completed": ("in_progress",)}


@router.post("/rides/{ride_id}/advance/{status}")
async def advance(ride_id: int, status: str, user: dict = Depends(require_driver)):
    ride = ride_for_participant(ride_id, user)
    if status not in DRIVER_STEPS:
        raise HTTPException(422, "Unknown ride step.")
    updated = set_status(ride_id, status, DRIVER_STEPS[status])
    if updated is None:
        raise HTTPException(409, f"A ride that is {ride['status']} cannot move to {status}.")
    if status == "completed":
        release_driver(user["id"])
    await broadcast_ride(updated)
    return ride_view(updated, user)


# ------------------------------------------------------------------ feedback
FEEDBACK_TAGS = {
    "safe": "Safe driving", "polite": "Polite driver", "clean": "Clean vehicle", "on_time": "On time",
    "route": "Good route", "late": "Driver was late", "rash": "Rash driving", "rude": "Rude behaviour",
    "dirty": "Vehicle not clean", "fare": "Fare issue",
}


class FeedbackBody(BaseModel):
    rating: int = Field(..., ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=len(FEEDBACK_TAGS))
    comment: str = Field("", max_length=500)


def feedback_for(ride_id: int) -> dict | None:
    with appdb.connect() as conn:
        row = conn.execute("SELECT rating, tags, comment, created_at FROM feedback WHERE ride_id = ?",
                           (ride_id,)).fetchone()
    return {**dict(row), "tags": json.loads(row["tags"])} if row else None


@router.post("/rides/{ride_id}/feedback")
def give_feedback(ride_id: int, body: FeedbackBody, user: dict = Depends(current_user)):
    """The rider rates a finished trip, once. Feedback is optional: skipping sends nothing."""
    ride = ride_for_participant(ride_id, user)
    if user["id"] != ride["rider_id"]:
        raise HTTPException(403, "Only the rider can rate this trip.")
    if ride["status"] != "completed":
        raise HTTPException(409, "You can rate a trip once it is completed.")
    unknown = [t for t in body.tags if t not in FEEDBACK_TAGS]
    if unknown:
        raise HTTPException(422, "Unknown feedback option.")
    tags = list(dict.fromkeys(body.tags))
    try:
        with appdb.connect() as conn:
            conn.execute("INSERT INTO feedback (ride_id, rider_id, rating, tags, comment, created_at) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (ride_id, user["id"], body.rating, json.dumps(tags), body.comment.strip(), time.time()))
    except appdb.IntegrityError:
        raise HTTPException(409, "You have already rated this trip.")
    return {"message": "Thank you for your feedback!", "feedback": feedback_for(ride_id)}


# ------------------------------------------------------------------ chat
class MessageBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=500)


HELP_TOPICS = {
    "safety": "I feel unsafe",
    "driver": "Problem with the driver",
    "rider": "Problem with the rider",
    "route": "Wrong route or stop",
    "vehicle": "Vehicle problem or breakdown",
    "payment": "Fare or payment",
    "other": "Something else",
}
HELP_PER_RIDE = 10


class HelpBody(BaseModel):
    topic: str
    note: str = Field("", max_length=500)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)


@router.post("/rides/{ride_id}/help")
async def ask_for_help(ride_id: int, body: HelpBody, user: dict = Depends(current_user)):
    """A rider or driver asks Raahi support for help during a ride. Admins see it live."""
    ride = ride_for_participant(ride_id, user)
    if user["role"] == "admin":
        raise HTTPException(403, "Only the rider or driver can ask for help.")
    if body.topic not in HELP_TOPICS:
        raise HTTPException(422, "Choose what you need help with.")
    if ride["status"] not in ACTIVE:
        raise HTTPException(409, "Help requests are for rides that are still going.")
    note = body.note.strip()
    if body.lat is not None and body.lon is not None:
        note = f"{note} [location {body.lat:.5f}, {body.lon:.5f}]".strip()
    with appdb.connect() as conn:
        sent = conn.execute("SELECT COUNT(*) AS n FROM help_requests WHERE ride_id = ? AND user_id = ?",
                            (ride_id, user["id"])).fetchone()["n"]
        if sent >= HELP_PER_RIDE:
            raise HTTPException(429, "You have sent several requests for this ride. For urgent help, call 112.")
        now = time.time()
        cursor = conn.execute(
            "INSERT INTO help_requests (ride_id, user_id, role, topic, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (ride_id, user["id"], user["role"], body.topic, note, now))
    request = help_view({"id": cursor.lastrowid, "ride_id": ride_id, "role": user["role"], "topic": body.topic,
                         "note": note, "created_at": now, "name": user["name"], "phone": user["phone"],
                         "pickup": ride["pickup"], "dropoff": ride["dropoff"], "status": ride["status"]})
    for admin_id in list(hub.admins):
        await hub.send(admin_id, {"type": "help", "help": request})
    return {"id": request["id"], "message": "Raahi support has your request and will contact you shortly."}


def place_name(place) -> str:
    return (place if isinstance(place, dict) else json.loads(place)).get("name") or "Map pin"


def help_view(row: dict) -> dict:
    return {"id": row["id"], "ride_id": row["ride_id"], "role": row["role"], "topic": row["topic"],
            "topic_label": HELP_TOPICS.get(row["topic"], row["topic"]), "note": row["note"],
            "created_at": row["created_at"], "name": row["name"], "phone": row["phone"],
            "route": f"{place_name(row['pickup'])} → {place_name(row['dropoff'])}", "ride_status": row["status"]}


@router.get("/admin/help")
def help_requests(admin: dict = Depends(require_admin)):
    with appdb.connect() as conn:
        rows = conn.execute(
            "SELECT h.*, u.name, u.phone, r.pickup, r.dropoff, r.status FROM help_requests h "
            "JOIN users u ON u.id = h.user_id JOIN rides r ON r.id = h.ride_id "
            "ORDER BY h.created_at DESC LIMIT 50").fetchall()
    return [help_view(dict(r)) for r in rows]


def save_message(ride_id: int, sender: str, body: str) -> dict:
    now = time.time()
    with appdb.connect() as conn:
        message_id = conn.execute(
            "INSERT INTO messages (ride_id, sender, body, created_at) VALUES (?, ?, ?, ?)",
            (ride_id, sender, body, now)).lastrowid
    return {"id": message_id, "ride_id": ride_id, "sender": sender, "body": body, "created_at": now}


@router.get("/rides/{ride_id}/messages")
def messages(ride_id: int, user: dict = Depends(current_user)):
    ride_for_participant(ride_id, user)
    with appdb.connect() as conn:
        rows = conn.execute("SELECT * FROM messages WHERE ride_id = ? ORDER BY id", (ride_id,)).fetchall()
    return [dict(r) for r in rows]


@router.post("/rides/{ride_id}/messages")
async def send_message(ride_id: int, body: MessageBody, user: dict = Depends(current_user)):
    ride = ride_for_participant(ride_id, user)
    if user["role"] == "admin":
        raise HTTPException(403, "Admins cannot post in a ride chat.")
    if ride["status"] not in ("accepted", "arrived", "in_progress"):
        raise HTTPException(409, "Chat is open only during a ride.")
    message = save_message(ride_id, "driver" if user["role"] == "driver" else "rider", body.body.strip())
    await hub.to_ride(ride, {"type": "message", "message": message})
    if ride["sim_driver"]:
        asyncio.create_task(simulated_reply(ride, len(body.body)))
    return message


async def simulated_reply(ride: dict, seed: int):
    await asyncio.sleep(1.5)
    reply = save_message(ride["id"], "driver", SIM_REPLIES[seed % len(SIM_REPLIES)])
    await hub.to_ride(ride, {"type": "message", "message": reply})


# ------------------------------------------------------------------ addresses
@router.get("/address")
async def address_search(q: str = Query(..., min_length=2, max_length=120), near_lat: float | None = None,
                         near_lon: float | None = None, user: dict = Depends(current_user)):
    """Places matching typed text: known places, our neighbourhood list, then OpenStreetMap."""
    results = []
    known = _known_place(q)
    if known:
        results.append(known)
    near = {"lat": near_lat, "lon": near_lon} if near_lat is not None and near_lon is not None else None
    local = localities.lookup(q)
    if local and not local["approx"]:
        results.append(local)
    results += placesdb.search(q, near)
    if local and local["approx"]:
        results.append(local)
    if not results:
        results += await geocode.search(q, near)
    unique = {(r["name"], round(r["lat"], 2), round(r["lon"], 2)): r for r in reversed(results)}
    return list(reversed(unique.values()))[:6]


@router.get("/address/reverse")
async def address_reverse(lat: float, lon: float, user: dict = Depends(current_user)):
    return {"name": await describe_point(lat, lon)}


async def describe_point(lat: float, lon: float) -> str:
    return await geocode.describe(lat, lon) or f"Near {nearest_place(lat, lon)['name']}"


def _known_place(text: str) -> dict | None:
    name = chatbot.parse(text).place
    return chat_point(name) if name in BY_NAME else None


# ------------------------------------------------------------------ assistant
class ChatBody(BaseModel):
    message: str = Field("", max_length=500)
    location: Point | None = None     # the rider's position, when the app was asked for it
    target: str = "pickup"
    women_only: bool = False          # the app is in Women Raahi mode


def chat_point(name: str) -> dict:
    place = BY_NAME[name]
    return {"lat": place["lat"], "lon": place["lon"], "name": name}


def chat_route(chat: dict) -> dict:
    """Price the trip in the conversation. Errors become a sentence in the rider's language."""
    def point(p):
        return Point(lat=p["lat"], lon=p["lon"], name=p["name"][:120])
    return build_quote(QuoteBody(pickup=point(chat["pickup"]), dropoff=point(chat["dropoff"])))


def first_name(user: dict) -> str:
    return user["name"].split()[0]


def home_of(user: dict) -> dict | None:
    return appdb.get_setting(f"home:{user['id']}")


async def resolve_place(text: str, user: dict, near: dict | None, strict: bool = False) -> dict | None:
    """
    Turn what the rider said into a point, or None rather than a guess. Several far-apart
    places with the same name come back as {"choices": [...]} for the rider to pick from.
    """
    if text == chatbot.HOME:
        return home_of(user)
    if text in BY_NAME:
        return chat_point(text)
    local = localities.lookup(text)
    if local and not local["approx"]:
        return local
    results = placesdb.search(text, near, strict=strict)
    if results:
        return results[0] if near or placesdb.is_clear_winner(results) else {"choices": results[:4]}
    if local:
        return local
    if strict:
        return None
    results = await geocode.search(text, near)
    return results[0] if results else None


def explain_quote_error(lang: str, error: HTTPException) -> str:
    detail = str(error.detail)
    if error.status_code == 409 and "Road closed" in detail:
        return chatbot.say(lang, "closed", detail=detail)
    if "outside" in detail:
        return chatbot.say(lang, "outside")
    if "too close" in detail:
        return chatbot.say(lang, "too_close")
    return chatbot.say(lang, "failed", detail=detail)


def recommendation_note(lang: str, option: dict) -> str | None:
    rec = option["recommendation"]
    if not rec["confident"]:
        return None
    if rec["pick"] == "raahi":
        return chatbot.say(lang, "rec_us")
    rival = next(r["label"] for r in option["rivals"] if r["id"] == rec["pick"])
    return chatbot.say(lang, "rec_rival", rival=rival)


def active_ride_reply(chat: dict, user: dict, ride: dict, parsed: chatbot.Parsed) -> dict:
    lang = chat["lang"]
    names = {"pickup": ride["pickup"]["name"], "dropoff": ride["dropoff"]["name"]}
    if parsed.call:
        driver = ride_view(ride, user)["driver"]
        if driver is None:
            return {"text": chatbot.say(lang, "call_wait")}
        if driver["simulated"]:
            return {"text": chatbot.say(lang, "call_simulated", driver=driver["name"])}
        return {"text": chatbot.say(lang, "calling", driver=driver["name"]), "call": driver["phone"]}
    if parsed.cancel:
        if ride["status"] == "in_progress":
            return {"text": chatbot.say(lang, "cant_cancel")}
        chat["awaiting"] = "cancel"
        labels = chatbot.BUTTON_LABELS[lang]
        return {"text": chatbot.say(lang, "confirm_cancel", **names),
                "buttons": [{"label": labels["no"], "send": "no"}, {"label": "✓", "send": "yes"}]}
    driver = ride_view(ride, user)["driver"]
    return {"text": chatbot.say(lang, ride["status"], driver=driver["name"] if driver else "", **names)}


@router.post("/chat")
async def chat_message(body: ChatBody, user: dict = Depends(current_user)):
    if user["role"] != "rider":
        raise HTTPException(403, "The assistant is for rider accounts.")
    reply = await chat_reply(body, user)
    # The app reads this aloud, in the right voice, the way a person would say it.
    lang = hub.chats[user["id"]]["lang"]
    return {**reply, "lang": lang, "speech": chatbot.spoken(reply["text"], lang)}


def trip_history_text(user: dict, lang: str) -> str:
    with appdb.connect() as conn:
        rows = conn.execute("SELECT dropoff, fare FROM rides WHERE rider_id = ? AND status = 'completed' "
                            "ORDER BY id DESC LIMIT 3", (user["id"],)).fetchall()
    if not rows:
        return chatbot.say(lang, "no_history")
    trips = ", ".join(f"{chatbot.place_label(json.loads(r['dropoff'])['name'], lang)} ₹{r['fare']}" for r in rows)
    return chatbot.say(lang, "history", trips=trips)


def place_buttons(lang: str, target: str, user: dict) -> list:
    buttons = []
    if target == "pickup":
        buttons.append({"label": chatbot.say(lang, "btn_here"), "action": "location", "target": "pickup"})
    if home_of(user):
        buttons.append({"label": chatbot.say(lang, "btn_home"), "send": "ghar se" if target == "pickup" else "ghar jana hai"})
    buttons.append({"label": chatbot.say(lang, "btn_map"), "action": "map", "target": target,
                    "prompt": chatbot.say(lang, "pin_prompt")})
    return buttons


def new_chat() -> dict:
    return {"lang": "en", "pickup": None, "dropoff": None, "vehicle": None, "awaiting": None,
            "asking": None, "turn": 0}


@router.get("/chat/hello")
def chat_hello(lang: str = "en", user: dict = Depends(current_user)):
    """A personal opening: the rider's name, the time of day, and where they last went."""
    chat = hub.chats.setdefault(user["id"], new_chat())
    if lang in chatbot.REPLIES:
        chat["lang"] = lang
    lang = chat["lang"]
    with appdb.connect() as conn:
        last = conn.execute("SELECT dropoff FROM rides WHERE rider_id = ? AND status = 'completed' ORDER BY id DESC LIMIT 1",
                            (user["id"],)).fetchone()
    greeting = chatbot.greeting_for(lang, now_ist().hour)
    buttons = [{"label": chatbot.say(lang, "btn_here"), "action": "location", "target": "pickup"}]
    if home_of(user):
        buttons.append({"label": chatbot.say(lang, "btn_home"), "send": "ghar jana hai"})
    if last:
        place = json.loads(last["dropoff"])["name"]
        label = chatbot.place_label(place, lang)
        buttons.append({"label": label, "send": f"to {place}", "lang_keep": True})
        text = chatbot.say(lang, "hello_again", greeting=greeting, name=first_name(user), place=label)
    else:
        text = chatbot.say(lang, "hello", greeting=greeting, name=first_name(user))
    return {"text": text, "speech": chatbot.spoken(text, lang), "lang": lang, "buttons": buttons}


async def apply_place(chat: dict, target: str, text: str, user: dict, lang: str) -> dict | None:
    """Set one end of the trip. Returns a reply if that couldn't be done."""
    if text == chatbot.HOME and not home_of(user):
        chat["asking"] = None
        return {"text": chatbot.say(lang, "ask_home")}
    other = chat["dropoff" if target == "pickup" else "pickup"]
    point = await resolve_place(text, user, other)
    if point is None:
        chat["asking"] = target
        return {"text": chatbot.say(lang, "not_found", place=text), "buttons": place_buttons(lang, target, user), "listen": True}
    if "choices" in point:
        chat["asking"] = target
        return {"text": chatbot.say(lang, "which_one"), "listen": False,
                "buttons": [{"label": f"{c['name']} · {c['town']}", "action": "point", "target": target,
                             "point": {"lat": c["lat"], "lon": c["lon"], "name": c["name"]}} for c in point["choices"]]}
    chat[target] = point
    return None


async def chat_reply(body: ChatBody, user: dict) -> dict:
    parsed = chatbot.parse(body.message)
    chat = hub.chats.setdefault(user["id"], new_chat())
    chat["lang"] = parsed.lang or chat["lang"]
    chat["turn"] += 1
    lang = chat["lang"]

    if parsed.history:
        return {"text": trip_history_text(user, lang)}

    ride = active_ride_for(user)
    if not ride and (parsed.status or parsed.call) and not parsed.has_place and not parsed.free:
        return {"text": chatbot.say(lang, "no_ride")}
    if ride:
        if chat["awaiting"] == "cancel" and (parsed.confirm or parsed.deny):
            chat["awaiting"] = None
            if parsed.deny and not parsed.cancel:
                return {"text": chatbot.say(lang, "kept")}
            if set_status(ride["id"], "cancelled", ("searching", "accepted", "arrived")) is None:
                return {"text": chatbot.say(lang, "cant_cancel")}
            release_driver(ride["driver_id"])
            await broadcast_ride(get_ride(ride["id"]))
            return {"text": chatbot.say(lang, "cancelled"), "refresh": True}
        return active_ride_reply(chat, user, ride, parsed)

    # "Where is Bawe Wali Mata?" is answered, and the place is ready to go to.
    asked_about = parsed.free or parsed.place or parsed.dropoff
    if parsed.status and asked_about and not parsed.pickup and asked_about not in (chatbot.CURRENT, chatbot.HOME):
        point = await resolve_place(asked_about, user, None)
        if point is None:
            return {"text": chatbot.say(lang, "not_found", place=asked_about), "buttons": place_buttons(lang, "dropoff", user)}
        if "choices" in point:
            return {"text": chatbot.say(lang, "which_one"),
                    "buttons": [{"label": f"{c['name']} · {c['town']}", "action": "point", "target": "dropoff",
                                 "point": {"lat": c["lat"], "lon": c["lon"], "name": c["name"]}} for c in point["choices"]]}
        chat.update(dropoff=point, pickup=None, vehicle=None, asking="pickup", awaiting=None)
        town = point.get("town") or nearest_place(point["lat"], point["lon"])["name"]
        return {"dropoff": point, "text": chatbot.say(lang, "where_is", place=point["name"], town=town),
                "buttons": place_buttons(lang, "pickup", user), "listen": True}

    # The app has sent the rider's position or a map pin.
    if body.location:
        if body.target not in ("pickup", "dropoff"):
            raise HTTPException(422, "Unknown trip end.")
        if not in_service_area(body.location.lat, body.location.lon):
            chat["asking"] = body.target
            return {"text": chatbot.say(lang, "outside"), "buttons": place_buttons(lang, body.target, user)}
        name = body.location.name or await describe_point(body.location.lat, body.location.lon)
        chat[body.target] = {"lat": body.location.lat, "lon": body.location.lon, "name": name[:120]}
        chat["asking"] = None
        said_here = body.target == "pickup" and not body.location.name
        return await next_step(chat, user, lang, parsed, chatbot.say(lang, "located", pickup=name) if said_here else None)

    # "Book a cab to X" is a new request, so only a bare yes can book the pending fare.
    if parsed.confirm and chat["awaiting"] == "book" and not parsed.has_place and not parsed.free and not parsed.vehicle:
        chat["awaiting"] = None
        try:
            quoted = chat_route(chat)
        except HTTPException as error:
            return {"text": explain_quote_error(lang, error)}
        option = next((o for o in quoted["options"] if o["vehicle"] == chat["vehicle"]), None)
        if option is None:
            return {"text": chatbot.say(lang, "not_offered", vehicle=chatbot.VEHICLE_NAMES[lang][chat["vehicle"]])}
        check_women_only(user, body.women_only)
        created = await create_ride(user, quoted, option, body.women_only)
        text = chatbot.say(lang, "booked", fare=created["fare"], pickup=chat["pickup"]["name"], dropoff=chat["dropoff"]["name"])
        chat.update(pickup=None, dropoff=None, vehicle=None, asking=None)
        return {"text": text, "ride": ride_view(created, user)}

    if parsed.deny and not parsed.has_place:
        chat.update(pickup=None, dropoff=None, vehicle=None, awaiting=None, asking=None)
        return {"text": chatbot.say(lang, "dropped"), "listen": True, "cleared": True}

    if parsed.temples:
        temples = json.loads((FRONTEND_PHOTOS / "photos.json").read_text(encoding="utf-8"))
        return {"text": chatbot.say(lang, "temples"), "temples": [p["id"] for p in temples if p["category"] == "temple"]}

    if parsed.save_home:
        point = await resolve_place(parsed.save_home, user, None)
        if point is None:
            return {"text": chatbot.say(lang, "not_found", place=parsed.save_home),
                    "buttons": place_buttons(lang, "dropoff", user)}
        appdb.set_setting(f"home:{user['id']}", {**point, "name": point["name"]})
        return {"text": chatbot.say(lang, "home_saved", name=first_name(user), place=point["name"])}

    # A fresh full request replaces the old trip.
    if parsed.pickup and parsed.dropoff:
        chat.update(vehicle=None, pickup=None, dropoff=None)
    chat["vehicle"] = parsed.vehicle or chat["vehicle"]
    chat["awaiting"] = None

    # A lone place answers the open question; otherwise it's where they want to go.
    lone = parsed.place or (parsed.free if chat["asking"] else None)
    if lone:
        target = chat["asking"] or ("pickup" if chat["dropoff"] and not chat["pickup"] else "dropoff")
        if lone == chatbot.CURRENT:
            target = "pickup"
        if target == "pickup":
            parsed.pickup = lone
        else:
            parsed.dropoff = lone
    elif parsed.free:
        # With nothing asked yet, only a known area counts, so chatter isn't searched as an address.
        found = await resolve_place(parsed.free, user, chat["pickup"], strict=True)
        if found:
            parsed.dropoff = parsed.free

    # Do the drop-off first: "here" stops to ask the browser, and shouldn't lose it.
    if parsed.dropoff:
        problem = await apply_place(chat, "dropoff", parsed.dropoff, user, lang)
        if problem:
            return problem
    if parsed.pickup == chatbot.CURRENT:
        return {**trip_points(chat), "text": chatbot.say(lang, "locating"), "need_location": "pickup",
                "failed_buttons": place_buttons(lang, "pickup", user)}
    if parsed.pickup:
        problem = await apply_place(chat, "pickup", parsed.pickup, user, lang)
        if problem:
            return problem
    chat["asking"] = None

    if not chat["pickup"] and not chat["dropoff"]:
        return {"text": chatbot.say(lang, "greet" if parsed.greet else "help"), "listen": True}
    return await next_step(chat, user, lang, parsed, None)


def trip_points(chat: dict) -> dict:
    return {k: chat[k] for k in ("pickup", "dropoff") if chat[k]}


async def next_step(chat: dict, user: dict, lang: str, parsed: chatbot.Parsed, opener: str | None) -> dict:
    """Ask for what's missing, or give the fare. Only one question at a time, like a person."""
    def lead(text: str) -> str:
        return f"{opener} {text}" if opener else chatbot.with_ack(lang, text, chat["turn"])

    reply = trip_points(chat)
    if not chat["pickup"]:
        chat["asking"] = "pickup"
        return {**reply, "text": lead(chatbot.say(lang, "ask_pickup", dropoff=chat["dropoff"]["name"])),
                "buttons": place_buttons(lang, "pickup", user), "listen": True}
    if not chat["dropoff"]:
        chat["asking"] = "dropoff"
        return {**reply, "text": lead(chatbot.say(lang, "ask_dropoff", pickup=chat["pickup"]["name"])),
                "buttons": place_buttons(lang, "dropoff", user), "listen": True}
    chat["asking"] = None

    try:
        quoted = chat_route(chat)
    except HTTPException as error:
        chat.update(dropoff=None, vehicle=None)
        return {"text": explain_quote_error(lang, error)}

    approx = next((p for p in (chat["pickup"], chat["dropoff"]) if p.get("approx") and p.get("area")), None)
    note = chatbot.say(lang, "approx", area=approx["area"]) if approx else None
    names = chatbot.VEHICLE_NAMES[lang]
    trip = {"pickup": chat["pickup"]["name"], "dropoff": chat["dropoff"]["name"], "km": quoted["km"]}
    best = None
    if parsed.cheapest:
        best = min(quoted["options"], key=lambda o: o["fare"])
        chat["vehicle"] = best["vehicle"]
    option = next((o for o in quoted["options"] if o["vehicle"] == chat["vehicle"]), None)
    if option is None:
        buttons = [{"label": f"{names[o['vehicle']]} · ₹{o['fare']}", "send": o["vehicle"]} for o in quoted["options"]]
        text = (chatbot.say(lang, "not_offered", vehicle=names[chat["vehicle"]]) if chat["vehicle"]
                else chatbot.say(lang, "ask_vehicle", **trip))
        chat["vehicle"] = None
        return {**reply, "path": quoted["path"], "text": lead(text), "note": note, "buttons": buttons, "listen": True}

    chat["awaiting"] = "book"
    labels = chatbot.BUTTON_LABELS[lang]
    rec = recommendation_note(lang, option)
    return {**reply, "path": quoted["path"],
            "text": lead(chatbot.say(lang, "best_value" if best else "confirm", vehicle=names[option["vehicle"]], fare=option["fare"], **trip)),
            "note": " ".join(n for n in (note, rec) if n) or None,
            "buttons": [{"label": labels["no"], "send": "no"}, {"label": labels["yes"], "send": "yes"}]}


# ------------------------------------------------------------------ admin
class ConditionsBody(BaseModel):
    temperature: float = Field(..., ge=-30, le=55)
    precipitation: float = Field(..., ge=0, le=100)
    weather_condition: str
    road_closed: bool = False
    pilgrim_override: float | None = Field(None, ge=0, le=1)
    hour_override: int | None = Field(None, ge=0, le=23)


class CapsBody(BaseModel):
    normal: float = Field(..., ge=1.0, le=1.4)
    hardship: float = Field(..., ge=1.0, le=1.4)


@router.get("/admin/overview")
def admin_overview(admin: dict = Depends(require_admin)):
    with appdb.connect() as conn:
        totals = dict(conn.execute(
            "SELECT COUNT(*) AS rides, "
            "COALESCE(SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END), 0) AS completed, "
            "COALESCE(SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END), 0) AS cancelled, "
            "COALESCE(SUM(CASE WHEN status = 'completed' THEN fare ELSE 0 END), 0) AS fares "
            "FROM rides").fetchone())
        users = {r["role"]: r["n"] for r in conn.execute(
            "SELECT role, COUNT(*) AS n FROM users GROUP BY role").fetchall()}
        by_region = [dict(r) for r in conn.execute(
            "SELECT region, COUNT(*) AS rides, COALESCE(SUM(fare), 0) AS fares FROM rides "
            "WHERE status = 'completed' GROUP BY region").fetchall()]
        recent = [row_to_ride(r) for r in conn.execute(
            "SELECT * FROM rides ORDER BY id DESC LIMIT 25").fetchall()]
        ratings = dict(conn.execute("SELECT COUNT(*) AS n, AVG(rating) AS average FROM feedback").fetchone())
    return {
        "ratings": {"count": ratings["n"], "average": round(float(ratings["average"]), 2) if ratings["n"] else None},
        **totals, "users": users, "by_region": by_region,
        "drivers_online": len(hub.drivers),
        "rides_capped": sum(1 for r in recent if r["quote"]["fair_capped"]),
        "recent": [ride_view(r, admin) for r in recent],
    }


@router.get("/admin/conditions")
def admin_conditions(admin: dict = Depends(require_admin)):
    return {"regions": {r: {**conditions_for(r), "name": REGIONS[r]["name"]} for r in REGIONS},
            "caps": fair_caps(), "rival_rates": rival_rates()}


@router.put("/admin/conditions/{region}")
def set_conditions(region: str, body: ConditionsBody, admin: dict = Depends(require_admin)):
    if region not in REGIONS:
        raise HTTPException(404, "Unknown region.")
    if body.weather_condition not in ("Clear", "Cloudy", "Rainy", "Stormy", "Snowy"):
        raise HTTPException(422, "Unknown weather condition.")
    appdb.set_setting(f"conditions:{region}", body.model_dump())
    return conditions_for(region)


@router.put("/admin/caps")
def set_caps(body: CapsBody, admin: dict = Depends(require_admin)):
    if body.hardship > body.normal:
        raise HTTPException(422, "The hardship cap cannot be above the normal cap.")
    appdb.set_setting("fair_caps", body.model_dump())
    return fair_caps()


class RateCard(BaseModel):
    base: float = Field(..., ge=0, le=1000)
    per_km: float = Field(..., ge=0, le=200)


@router.put("/admin/rival-rates/{rival}/{vehicle}")
def set_rival_rate(rival: str, vehicle: str, body: RateCard, admin: dict = Depends(require_admin)):
    rates = rival_rates()
    if rival not in rates or vehicle not in rates[rival]["cards"]:
        raise HTTPException(404, "Unknown rival or vehicle.")
    rates[rival]["cards"][vehicle] = body.model_dump()
    appdb.set_setting("rival_rates", rates)
    return rates[rival]


def business_assumptions() -> dict:
    return business.merge(appdb.get_setting("business_model"))


def economics_of(ride: dict) -> dict:
    quote = ride["quote"]
    return business.ride_economics(ride["fare"], ride["km"], ride["vehicle"], quote.get("normal_fare"),
                                   quote.get("business") or business_assumptions())


@router.get("/admin/business")
def admin_business(admin: dict = Depends(require_admin)):
    """Per-ride business model: revenue, costs and profit of every ride, plus totals."""
    with appdb.connect() as conn:
        rows = [row_to_ride(r) for r in conn.execute(
            "SELECT * FROM rides ORDER BY id DESC LIMIT 5000").fetchall()]
    completed = [r for r in rows if r["status"] == "completed"]
    done_econ = [economics_of(r) for r in completed]

    by_vehicle = {}
    for ride, econ in zip(completed, done_econ):
        by_vehicle.setdefault(ride["vehicle"], []).append(econ)

    recent = []
    for ride in rows[:50]:
        view = ride_view(ride, admin)
        recent.append({
            "id": ride["id"], "created_at": ride["created_at"], "status": ride["status"],
            "trip": f"{ride['pickup']['name']} → {ride['dropoff']['name']}",
            "vehicle": ride["vehicle"], "label": ride["quote"]["label"], "km": ride["km"],
            "multiplier": ride["quote"]["multiplier"],
            "driver": view["driver"]["name"] if view["driver"] else None,
            "simulated": bool(ride["sim_driver"]),
            # Cancelled or unfinished rides earn nothing yet; show what they would have.
            "counted": ride["status"] == "completed",
            "economics": economics_of(ride),
        })

    assumptions = business_assumptions()
    sample = {v: business.ride_economics(VEHICLES[v]["base"] + VEHICLES[v]["per_km"] * 10, 10, v,
                                         VEHICLES[v]["base"] + VEHICLES[v]["per_km"] * 10, assumptions)
              for v in VEHICLES}
    return {
        "assumptions": assumptions,
        "totals": business.summarise(done_econ),
        "by_vehicle": {v: {"label": VEHICLES[v]["label"], **business.summarise(e)} for v, e in by_vehicle.items()},
        "sample_10km": sample,
        "rides": recent,
    }


@router.put("/admin/business")
def set_business(body: dict, admin: dict = Depends(require_admin)):
    try:
        clean = business.validate(body)
    except ValueError as error:
        raise HTTPException(422, str(error))
    appdb.set_setting("business_model", clean)
    return clean


@router.get("/admin/simulation")
def simulation(admin: dict = Depends(require_admin)):
    path = OUTPUT_DIR / "simulation.json"
    if not path.exists():
        raise HTTPException(404, "Run python data_pipeline/simulate.py first.")
    return json.loads(path.read_text())


# ------------------------------------------------------------------ live updates
@router.websocket("/ws")
async def live(ws: WebSocket, token: str = ""):
    user = user_from_token(token)
    if user is None:
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.sockets.setdefault(user["id"], set()).add(ws)
    if user["role"] == "admin":
        hub.admins.add(user["id"])
    try:
        while True:
            await ws.receive_text()     # keep-alive pings from the client
    except WebSocketDisconnect:
        pass
    finally:
        hub.sockets[user["id"]].discard(ws)
        if not hub.sockets[user["id"]]:
            hub.admins.discard(user["id"])
            # A driver nobody can reach would hold every new offer until it timed out.
            # The app goes back online by itself when it reconnects.
            hub.drivers.pop(user["id"], None)


def cancel_interrupted_rides():
    """Trips run as in-memory tasks, so a restart would otherwise strand them forever."""
    with appdb.connect() as conn:
        conn.execute(
            f"UPDATE rides SET status = 'cancelled', updated_at = ? "
            f"WHERE status IN ({', '.join('?' * len(ACTIVE))})", (time.time(), *ACTIVE))
