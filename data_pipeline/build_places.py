"""
Build the J&K map data the app searches offline, from OpenStreetMap:

  * data/jk_places.json.gz   every named place a rider could be picked up at or go to:
                             cities, villages, hamlets, mohallas, temples, mosques, schools,
                             hospitals, banks, shops, petrol pumps, bus stops, local roads...
  * data/jk_boundary.json.gz the J&K boundary, so a pin anywhere inside it can be booked.

    python data_pipeline/build_places.py                         # downloads through Overpass
    python data_pipeline/build_places.py places.json boundary.json  # reuses saved answers

Data (c) OpenStreetMap contributors, under the Open Database License (ODbL). The query is
limited to OSM's J&K boundary, so places across the border stay out.
"""
import gzip
import json
import math
import sys
import urllib.parse
import urllib.request

from config import DATA_DIR

OUT = DATA_DIR / "jk_places.json.gz"
BOUNDARY_OUT = DATA_DIR / "jk_boundary.json.gz"
OVERPASS = "https://overpass-api.de/api/interpreter"
AGENT = "Raahi-college-demo/1.0 (student major project)"

# Everything with a name; build() drops what nobody would book a ride to.
PLACES_QUERY = """[out:json][timeout:250];
area["ISO3166-2"="IN-JK"]->.jk;
(nwr["name"](area.jk););
out tags center bb;"""
BOUNDARY_QUERY = """[out:json][timeout:250];
rel["ISO3166-2"="IN-JK"]["boundary"="administrative"];
out geom;"""

# Lines and areas that have a name but are no place to stand: rivers, power lines, borders.
SKIP = {"waterway", "boundary", "power", "route", "pipeline", "barrier", "aerialway", "piste:type"}
SKIP_RAILWAY = {"rail", "proposed", "abandoned", "disused", "construction", "narrow_gauge", "subway", "light_rail"}
ROAD_MAX_KM = 3.0          # a short named road is a landmark; a highway across districts is not
AREA_MAX_KM = 8.0          # likewise a huge forest or landuse area
KEEP_LARGE = {"place", "natural", "tourism", "leisure", "aeroway", "amenity"}
AMENITY_KINDS = {"hospital", "college", "university", "bus_station", "school", "bank", "fuel", "police",
                 "pharmacy", "clinic", "restaurant", "marketplace", "atm", "post_office", "cinema",
                 "townhall", "courthouse", "library", "kindergarten", "doctors", "dentist", "cafe"}
BOUNDARY_TOLERANCE = 0.001   # about 100 m: plenty to tell J&K from its neighbours


def kind_of(tags: dict) -> str:
    amenity = tags.get("amenity")
    if amenity == "place_of_worship":
        return "worship"
    if "place" in tags:
        return tags["place"]
    if amenity in AMENITY_KINDS:
        return amenity
    if "healthcare" in tags:
        return "clinic"
    if tags.get("highway") in ("bus_stop", "bus_station"):
        return "bus_stop"
    if "highway" in tags:
        return "road"
    if tags.get("railway") in ("station", "halt"):
        return "railway"
    if tags.get("aeroway") in ("aerodrome", "terminal"):
        return "aeroway"
    if tags.get("tourism") in ("hotel", "guest_house", "hostel", "motel"):
        return "hotel"
    for key in ("tourism", "historic", "natural", "leisure"):
        if key in tags:
            return key
    if tags.get("shop") == "mall":
        return "mall"
    if "shop" in tags:
        return "shop"
    if "office" in tags:
        return "office"
    if amenity:
        return "amenity"
    return "landmark"


def extent_km(element: dict) -> float:
    b = element.get("bounds")
    if not b:
        return 0.0
    dlat = (b["maxlat"] - b["minlat"]) * 111
    dlon = (b["maxlon"] - b["minlon"]) * 111 * math.cos(math.radians(b["minlat"]))
    return math.hypot(dlat, dlon)


def is_bookable(tags: dict, element: dict) -> bool:
    if any(k in tags for k in SKIP) or tags.get("railway") in SKIP_RAILWAY:
        return False
    if tags.get("type") in ("route", "boundary", "waterway", "network"):
        return False
    size = extent_km(element)
    if "highway" in tags and tags["highway"] not in ("bus_stop", "bus_station"):
        return size <= ROAD_MAX_KM
    return size <= AREA_MAX_KM or any(k in tags for k in KEEP_LARGE)


def position(element: dict) -> tuple:
    """A node's own point; for a way or relation its centre, or the middle of its bounds."""
    if "lat" in element:
        return element["lat"], element["lon"]
    if "center" in element:
        return element["center"]["lat"], element["center"]["lon"]
    if "bounds" in element:
        b = element["bounds"]
        return (b["minlat"] + b["maxlat"]) / 2, (b["minlon"] + b["maxlon"]) / 2
    return None, None


def build(elements: list) -> list:
    rows, seen = [], {}
    for element in elements:
        tags = element.get("tags", {})
        lat, lon = position(element)
        name = tags.get("name", "").strip()
        if lat is None or len(name) < 3 or not is_bookable(tags, element):
            continue
        # The same place is often mapped twice, as a point and as a building.
        key = name.lower()
        if any(math.hypot(lat - a, lon - b) < 0.005 for a, b in seen.get(key, [])):
            continue
        seen.setdefault(key, []).append((lat, lon))
        others = [tags.get(t) for t in ("name:en", "alt_name", "old_name", "name:hi", "name:ur", "loc_name")]
        rows.append([name, round(lat, 5), round(lon, 5), kind_of(tags), [o for o in others if o]])
    return rows


# ---------------------------------------------------------------- boundary
def stitch(ways: list) -> list:
    """Join the boundary's way segments end to end into closed rings."""
    pending = [list(w) for w in ways if len(w) >= 2]
    rings = []
    while pending:
        ring = pending.pop()
        grown = True
        while ring[0] != ring[-1] and grown:
            grown = False
            for i, way in enumerate(pending):
                if way[0] == ring[-1]:
                    ring += way[1:]
                elif way[-1] == ring[-1]:
                    ring += way[-2::-1]
                elif way[-1] == ring[0]:
                    ring = way[:-1] + ring
                elif way[0] == ring[0]:
                    ring = way[:0:-1] + ring
                else:
                    continue
                pending.pop(i)
                grown = True
                break
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def simplify(points: list, tolerance: float) -> list:
    """Douglas-Peucker, iterative so long borders don't hit the recursion limit."""
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        start, end = stack.pop()
        (ay, ax), (by, bx) = points[start], points[end]
        length = math.hypot(bx - ax, by - ay)
        worst, index = 0.0, None
        for i in range(start + 1, end):
            py, px = points[i]
            if length == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                d = abs((bx - ax) * (ay - py) - (ax - px) * (by - ay)) / length
            if d > worst:
                worst, index = d, i
        if index is not None and worst > tolerance:
            keep[index] = True
            stack += [(start, index), (index, end)]
    return [p for p, k in zip(points, keep) if k]


def build_boundary(elements: list) -> dict:
    relation = next(e for e in elements if e["type"] == "relation")
    ways = [[(round(p["lat"], 6), round(p["lon"], 6)) for p in m["geometry"]]
            for m in relation["members"] if m["type"] == "way" and m.get("role") in ("outer", "inner", "")]
    rings = [simplify(r, BOUNDARY_TOLERANCE) for r in stitch(ways)]
    return {"name": relation["tags"].get("name"), "source": "OpenStreetMap contributors, ODbL",
            "rings": [[[round(lat, 4), round(lon, 4)] for lat, lon in r] for r in rings if len(r) >= 4]}


def overpass(query: str) -> dict:
    request = urllib.request.Request(OVERPASS, data=urllib.parse.urlencode({"data": query}).encode(),
                                     headers={"User-Agent": AGENT})
    return json.load(urllib.request.urlopen(request, timeout=300))


def main():
    saved = sys.argv[1:]
    places = json.load(open(saved[0], encoding="utf-8")) if saved else overpass(PLACES_QUERY)
    boundary = json.load(open(saved[1], encoding="utf-8")) if len(saved) > 1 else overpass(BOUNDARY_QUERY)

    rows = build(places["elements"])
    # A place OSM has since renamed or removed stays searchable: riders may still use the old name.
    previous = json.loads(gzip.open(OUT, "rt", encoding="utf-8").read()) if OUT.exists() else []
    names = {r[0].lower() for r in rows}
    kept = [r for r in previous if r[0].lower() not in names]
    rows += kept
    print(f"kept {len(kept)} places from the previous build that OSM no longer returns")
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(rows):,} places -> {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")

    shape = build_boundary(boundary["elements"])
    with gzip.open(BOUNDARY_OUT, "wt", encoding="utf-8") as f:
        json.dump(shape, f, separators=(",", ":"))
    points = sum(len(r) for r in shape["rings"])
    print(f"{len(shape['rings'])} boundary rings, {points:,} points -> {BOUNDARY_OUT} "
          f"({BOUNDARY_OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
