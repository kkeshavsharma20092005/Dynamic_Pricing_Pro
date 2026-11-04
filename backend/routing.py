"""
Real road routes from OSRM (OpenStreetMap road data), so the map follows the actual road
and fares use the road distance instead of a straight line times a guessed factor.

The public demo server (router.project-osrm.org) is free for light use with no key. Set
OSRM_URL to point at your own server, or ROAD_ROUTING=0 to turn this off (the tests do).
Any failure returns None and the caller falls back to its estimate, so a slow or down
routing service can never block a booking.
"""
import os
import time
from collections import OrderedDict

import httpx

OSRM_URL = os.environ.get("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
ENABLED = os.environ.get("ROAD_ROUTING", "1") != "0"
HEADERS = {"User-Agent": "Raahi-college-demo/1.0 (student major project)"}
TIMEOUT = 5.0
MAX_POINTS = 400          # enough for a smooth line; keeps ride rows and responses small
CACHE_SIZE = 500
BACKOFF_SECONDS = 60      # after a failure, use estimates for a minute instead of waiting

_cache: OrderedDict = OrderedDict()
_down_until = 0.0


def _thin(points: list) -> list:
    if len(points) <= MAX_POINTS:
        return points
    step = len(points) / (MAX_POINTS - 1)
    return [points[int(i * step)] for i in range(MAX_POINTS - 1)] + [points[-1]]


def road_route(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> dict | None:
    """{"km", "minutes", "path"} along roads, or None if routing is unavailable."""
    global _down_until
    if not ENABLED or time.monotonic() < _down_until:
        return None
    key = tuple(round(v, 4) for v in (a_lat, a_lon, b_lat, b_lon))
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]

    url = f"{OSRM_URL}/route/v1/driving/{a_lon:.6f},{a_lat:.6f};{b_lon:.6f},{b_lat:.6f}"
    try:
        response = httpx.get(url, params={"overview": "full", "geometries": "geojson"},
                             headers=HEADERS, timeout=TIMEOUT)
        data = response.json()
        if response.status_code != 200 or data.get("code") != "Ok" or not data.get("routes"):
            raise ValueError(data.get("code", response.status_code))
    except Exception as error:      # network, timeout, bad JSON, no route: all fall back
        print(f"[routing] OSRM unavailable ({error}); using estimated distance")
        _down_until = time.monotonic() + BACKOFF_SECONDS
        return None

    best = data["routes"][0]
    road = [[lat, lon] for lon, lat in best["geometry"]["coordinates"]]
    # The route starts and ends on the nearest road; draw the last few metres to the pins.
    path = _thin([[a_lat, a_lon], *road, [b_lat, b_lon]])
    result = {"km": round(best["distance"] / 1000, 1),
              "minutes": max(1, round(best["duration"] / 60)), "path": path}
    _cache[key] = result
    if len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)
    return result
