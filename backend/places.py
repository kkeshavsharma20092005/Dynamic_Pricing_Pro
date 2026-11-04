"""
Jammu & Kashmir geography for the ride app.

Trips follow real roads through OSRM (see routing.py): road distance, drive time and the
line drawn on the map. If routing is unavailable, the fallback is an estimate: straight-line
distance times a terrain factor, passing through the real corridor towns between regions.
"""
from math import asin, cos, radians, sin, sqrt

from config import REGIONS
from routing import road_route

# OSRM drive times assume free-flowing traffic. J&K city traffic, ghat sections and
# checkpoints are slower, so its times are stretched by this much.
TRAFFIC_FACTOR = 1.2

PLACES = [
    # Jammu plains
    ("Jammu City", 32.7266, 74.8570, "JMU"), ("Jammu Railway Station", 32.7059, 74.8786, "JMU"),
    ("Jammu Airport", 32.6891, 74.8374, "JMU"), ("Raghunath Bazaar", 32.7300, 74.8650, "JMU"),
    ("Gandhi Nagar, Jammu", 32.7100, 74.8600, "JMU"), ("Katra", 32.9916, 74.9318, "JMU"),
    ("Samba", 32.5625, 75.1199, "JMU"), ("Kathua", 32.3699, 75.5209, "JMU"),
    ("Akhnoor", 32.8667, 74.7333, "JMU"), ("Udhampur", 32.9160, 75.1416, "JMU"),
    ("Reasi", 33.0800, 74.8300, "JMU"), ("Bahu Fort", 32.7265, 74.8805, "JMU"),
    ("Raghunath Temple", 32.7300, 74.8640, "JMU"), ("Shiv Khori", 33.1900, 74.8700, "JMU"),
    ("Baba Dhansar", 33.0400, 74.9300, "JMU"), ("Krimchi Temples", 32.9700, 75.1000, "JMU"),
    ("Mansar Lake", 32.7000, 75.1500, "JMU"),
    # Chenab valley and Pir Panjal
    ("Rajouri", 33.3716, 74.3125, "HIL"), ("Poonch", 33.7700, 74.0900, "HIL"),
    ("Ramban", 33.2400, 75.2400, "HIL"), ("Banihal", 33.4300, 75.2000, "HIL"),
    ("Patnitop", 33.0800, 75.3300, "HIL"), ("Doda", 33.1500, 75.5500, "HIL"),
    ("Bhaderwah", 32.9800, 75.7100, "HIL"), ("Kishtwar", 33.3100, 75.7700, "HIL"),
    # Kashmir valley
    ("Srinagar, Lal Chowk", 34.0700, 74.8100, "KSH"), ("Srinagar Airport", 33.9871, 74.7742, "KSH"),
    ("Dal Gate", 34.0800, 74.8300, "KSH"), ("Hazratbal", 34.1300, 74.8400, "KSH"),
    ("Budgam", 34.0200, 74.7200, "KSH"), ("Ganderbal", 34.2300, 74.7800, "KSH"),
    ("Sonamarg", 34.3000, 75.2900, "KSH"), ("Gulmarg", 34.0500, 74.3800, "KSH"),
    ("Baramulla", 34.2000, 74.3400, "KSH"), ("Sopore", 34.3000, 74.4700, "KSH"),
    ("Uri", 34.0800, 74.0500, "KSH"), ("Bandipora", 34.4200, 74.6400, "KSH"),
    ("Kupwara", 34.5300, 74.2600, "KSH"), ("Pulwama", 33.8700, 74.9000, "KSH"),
    ("Awantipora", 33.9200, 75.0100, "KSH"), ("Shopian", 33.7200, 74.8300, "KSH"),
    ("Kulgam", 33.6400, 75.0200, "KSH"), ("Anantnag", 33.7300, 75.1500, "KSH"),
    ("Pahalgam", 34.0100, 75.3200, "KSH"), ("Betaab Valley", 34.0500, 75.3660, "KSH"),
    ("Nishat Bagh", 34.1253, 74.8806, "KSH"), ("Qazigund", 33.5900, 75.1600, "KSH"),
]

BY_NAME = {name: {"name": name, "lat": lat, "lon": lon, "region": region}
           for name, lat, lon, region in PLACES}

# Towns a trip between two regions passes through, listed from the first region's side.
CORRIDORS = {
    ("JMU", "KSH"): ["Udhampur", "Ramban", "Banihal", "Qazigund"],
    ("JMU", "HIL"): ["Udhampur"],
    ("HIL", "KSH"): ["Banihal", "Qazigund"],
}


def distance_km(a_lat, a_lon, b_lat, b_lon) -> float:
    """Straight-line (haversine) distance."""
    d_lat, d_lon = radians(b_lat - a_lat), radians(b_lon - a_lon)
    h = sin(d_lat / 2) ** 2 + cos(radians(a_lat)) * cos(radians(b_lat)) * sin(d_lon / 2) ** 2
    return 6371.0 * 2 * asin(sqrt(h))


def nearest_place(lat: float, lon: float) -> dict:
    return min(BY_NAME.values(), key=lambda p: distance_km(lat, lon, p["lat"], p["lon"]))


_coverage: set = set()


def set_coverage(cells: set):
    """Grid squares of about 11 km that hold a mapped J&K place."""
    _coverage.update(cells)


def in_service_area(lat: float, lon: float) -> bool:
    """Close to a J&K town, or in a square with J&K places. Approximate near a border."""
    p = nearest_place(lat, lon)
    if distance_km(lat, lon, p["lat"], p["lon"]) <= 12.0:
        return True
    return (round(lat * 10), round(lon * 10)) in _coverage


def corridor_between(region_a: str, region_b: str) -> list:
    if (region_a, region_b) in CORRIDORS:
        return [BY_NAME[n] for n in CORRIDORS[(region_a, region_b)]]
    if (region_b, region_a) in CORRIDORS:
        return [BY_NAME[n] for n in reversed(CORRIDORS[(region_b, region_a)])]
    return []


def plan_route(a_lat, a_lon, b_lat, b_lon) -> dict:
    """Road distance, duration and the path to draw: routed if possible, else estimated."""
    start, end = nearest_place(a_lat, a_lon)["region"], nearest_place(b_lat, b_lon)["region"]
    via = [] if start == end else corridor_between(start, end)
    path = [(a_lat, a_lon)] + [(p["lat"], p["lon"]) for p in via] + [(b_lat, b_lon)]

    km = minutes = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(path, path[1:]):
        region = REGIONS[nearest_place((lat1 + lat2) / 2, (lon1 + lon2) / 2)["region"]]
        leg = distance_km(lat1, lon1, lat2, lon2) * region["road_factor"]
        km += leg
        minutes += leg / region["speed_kmph"] * 60

    # A Jammu-Kashmir trip crosses the hills even when no hill town is an endpoint.
    regions = {start, end} | ({"HIL"} if {start, end} == {"JMU", "KSH"} else set())
    result = {"km": round(km, 1), "minutes": round(minutes), "path": path, "routed": False,
              "start_region": start, "end_region": end, "regions": sorted(regions)}

    road = road_route(a_lat, a_lon, b_lat, b_lon)
    if road:
        result.update(km=road["km"], minutes=max(1, round(road["minutes"] * TRAFFIC_FACTOR)),
                      path=road["path"], routed=True)
    return result
