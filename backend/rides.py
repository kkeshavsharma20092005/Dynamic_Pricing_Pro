"""
The ride app: accounts, quotes, booking, dispatch, live tracking, chat and admin.

Dispatch tries real online drivers first, nearest first. If none accepts, a simulated
driver takes the ride, so a demo always completes. Simulated trips run at demo speed
(under a minute) whatever the distance. Everything is marked so the UI can say which
parts are simulated.
"""
import asyncio
import json
import os
import random
import re
import secrets
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, Header, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

import appdb
import chatbot
import geocode
import localities
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
OFFER_SECONDS = 15
REAL_DRIVER_RADIUS_KM = 30.0
SIM_NAMES = ["Rakesh Sharma", "Mohd Yousuf", "Bilal Ahmad", "Sunil Kumar", "Imran Lone",
             "Vikram Singh", "Tariq Mir", "Ajay Gupta", "Farooq Dar", "Ramesh Thakur"]
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
    role: str = "rider"
    vehicle: str | None = None


class LoginBody(BaseModel):
    phone: str
    password: str
    role: str = "rider"


def make_token(user: dict) -> str:
    expires = datetime.now(timezone.utc) + timedelta(days=TOKEN_DAYS)
    return jwt.encode({"sub": str(user["id"]), "exp": expires}, SECRET, algorithm="HS256")


def user_from_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    return appdb.get_user(int(payload["sub"]))


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
    return {k: user[k] for k in ("id", "phone", "name", "role", "vehicle")}


@router.post("/register")
def register(body: RegisterBody):
    if not re.fullmatch(r"[6-9]\d{9}", body.phone):
        raise HTTPException(422, "Enter a valid 10-digit mobile number.")
    if body.role not in ("rider", "driver"):
        raise HTTPException(422, "Role must be rider or driver.")
    if body.role == "driver" and body.vehicle not in VEHICLES:
        raise HTTPException(422, "Choose a vehicle type.")
    try:
        user_id = appdb.create_user(body.phone, body.name.strip(), body.role, body.password,
                                    body.vehicle if body.role == "driver" else None)
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"This number already has a {body.role} account.")
    user = appdb.get_user(user_id)
    return {"token": make_token(user), "user": public_user(user)}


@router.post("/login")
def login(body: LoginBody):
    user = appdb.verify_user(body.phone, body.password, body.role)
    if user is None:
        raise HTTPException(401, f"No {body.role} account matches that number and password.")
    return {"token": make_token(user), "user": public_user(user)}


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return public_user(user)


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
        "km": route["km"], "minutes": route["minutes"], "path": route["path"],
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


def row_to_ride(row) -> dict:
    ride = dict(row)
    for key in ("pickup", "dropoff", "quote", "path"):
        ride[key] = json.loads(ride[key])
    ride["sim_driver"] = json.loads(ride["sim_driver"]) if ride["sim_driver"] else None
    return ride


def get_ride(ride_id: int) -> dict | None:
    with appdb.connect() as conn:
        row = conn.execute("SELECT * FROM rides WHERE id = ?", (ride_id,)).fetchone()
    return row_to_ride(row) if row else None


def ride_view(ride: dict, viewer: dict) -> dict:
    """What this viewer may see. Phone numbers are shared only while a ride is live."""
    view = {k: ride[k] for k in ride if k not in ("rider_id", "driver_id")}
    live = ride["status"] in ("accepted", "arrived", "in_progress")
    if ride["sim_driver"]:
        view["driver"] = {"name": ride["sim_driver"]["name"], "simulated": True, "phone": None}
    elif ride["driver_id"]:
        driver = appdb.get_user(ride["driver_id"])
        view["driver"] = {"name": driver["name"], "simulated": False,
                          "phone": driver["phone"] if live else None}
    else:
        view["driver"] = None
    if viewer["role"] == "driver" or viewer["role"] == "admin":
        rider = appdb.get_user(ride["rider_id"])
        view["rider"] = {"name": rider["name"], "phone": rider["phone"] if live else None}
    return view


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

    # Re-priced here: a client-supplied fare must never be trusted.
    quoted = build_quote(body)
    option = next((o for o in quoted["options"] if o["vehicle"] == body.vehicle), None)
    if option is None:
        raise HTTPException(422, "That vehicle is not available for this trip.")
    ride = await create_ride(user, quoted, option)
    return ride_view(ride, user)


async def create_ride(user: dict, quoted: dict, option: dict) -> dict:
    now = time.time()
    with appdb.connect() as conn:
        ride_id = conn.execute(
            "INSERT INTO rides (rider_id, status, pickup, dropoff, vehicle, region, km, minutes, "
            "fare, quote, path, created_at, updated_at) VALUES (?, 'searching', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user["id"], json.dumps(quoted["pickup"]), json.dumps(quoted["dropoff"]), option["vehicle"],
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
async def dispatch(ride_id: int):
    ride = get_ride(ride_id)
    candidates = sorted(
        (d for d in hub.drivers.values()
         if not d["busy"] and d["vehicle"] == ride["vehicle"]
         and distance_km(ride["pickup"]["lat"], ride["pickup"]["lon"], d["lat"], d["lon"]) <= REAL_DRIVER_RADIUS_KM),
        key=lambda d: distance_km(ride["pickup"]["lat"], ride["pickup"]["lon"], d["lat"], d["lon"]))

    for driver in candidates:
        if driver["busy"] or driver["id"] not in hub.drivers:
            continue
        event = asyncio.Event()
        hub.offers[ride_id] = {"event": event, "driver": driver["id"]}
        await hub.send(driver["id"], {"type": "offer", "ride": ride_view(ride, appdb.get_user(driver["id"])),
                                      "seconds": OFFER_SECONDS})
        try:
            await asyncio.wait_for(event.wait(), OFFER_SECONDS)
        except asyncio.TimeoutError:
            await hub.send(driver["id"], {"type": "offer_gone", "ride_id": ride_id})
        hub.offers.pop(ride_id, None)
        current = get_ride(ride_id)
        if current["status"] != "searching":
            return    # accepted by a real driver, or cancelled

    await asyncio.sleep(2)
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
    sim_driver = {"name": rng.choice(SIM_NAMES), "start": start}

    ride = set_status(ride_id, "accepted", ("searching",), sim_driver=json.dumps(sim_driver))
    if ride is None:
        return
    await broadcast_ride(ride)
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
    if body.lat is None or body.lon is None:
        raise HTTPException(422, "Location is needed to go online.")
    if not in_service_area(body.lat, body.lon):
        raise HTTPException(422, "You are outside the Jammu & Kashmir service area.")
    ride = active_ride_for(user)
    hub.drivers[user["id"]] = {"id": user["id"], "vehicle": user["vehicle"], "lat": body.lat,
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
    offer = offer_for(ride_id, user)
    ride = set_status(ride_id, "accepted", ("searching",), driver_id=user["id"])
    if ride is None:
        raise HTTPException(409, "This ride is no longer available.")
    if user["id"] in hub.drivers:
        hub.drivers[user["id"]]["busy"] = True
    offer["event"].set()
    await broadcast_ride(ride)
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


# ------------------------------------------------------------------ chat
class MessageBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=500)


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
        created = await create_ride(user, quoted, option)
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
    return {
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
