"""
Build data/jk_places.json.gz: the named places of Jammu & Kashmir, from OpenStreetMap.

    python data_pipeline/build_places.py              # downloads through Overpass
    python data_pipeline/build_places.py saved.json   # reuses a saved Overpass answer

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
QUERY = """[out:json][timeout:170];
area["ISO3166-2"="IN-JK"]->.jk;
(
 nwr["place"~"^(city|town|village|hamlet|suburb|neighbourhood|quarter|locality)$"]["name"](area.jk);
 nwr["amenity"~"^(place_of_worship|hospital|college|university|bus_station|school)$"]["name"](area.jk);
 nwr["tourism"~"^(attraction|viewpoint|museum|hotel|picnic_site|theme_park)$"]["name"](area.jk);
 nwr["historic"]["name"](area.jk);
 nwr["railway"~"^(station|halt)$"]["name"](area.jk);
 nwr["aeroway"="aerodrome"]["name"](area.jk);
 nwr["natural"~"^(water|peak|cave_entrance|valley)$"]["name"](area.jk);
 nwr["leisure"~"^(park|stadium)$"]["name"](area.jk);
 nwr["shop"="mall"]["name"](area.jk);
);
out center tags;"""


def kind_of(tags: dict) -> str:
    if tags.get("amenity") == "place_of_worship":
        return "worship"
    for key in ("place", "amenity", "tourism", "historic", "railway", "aeroway", "natural", "leisure", "shop"):
        if key in tags:
            return tags[key] if key in ("place", "amenity") else key
    return "other"


def build(elements: list) -> list:
    rows, seen = [], {}
    for element in elements:
        tags = element.get("tags", {})
        lat = element.get("lat") or element.get("center", {}).get("lat")
        lon = element.get("lon") or element.get("center", {}).get("lon")
        name = tags.get("name", "").strip()
        if lat is None or len(name) < 3:
            continue
        # The same place is often mapped twice, as a point and as a building.
        key = name.lower()
        if any(math.hypot(lat - a, lon - b) < 0.005 for a, b in seen.get(key, [])):
            continue
        seen.setdefault(key, []).append((lat, lon))
        others = [tags.get(t) for t in ("name:en", "alt_name", "old_name", "name:hi", "name:ur")]
        rows.append([name, round(lat, 5), round(lon, 5), kind_of(tags), [o for o in others if o]])
    return rows


def main():
    if len(sys.argv) > 1:
        answer = json.load(open(sys.argv[1], encoding="utf-8"))
    else:
        request = urllib.request.Request(
            "https://overpass-api.de/api/interpreter",
            data=urllib.parse.urlencode({"data": QUERY}).encode(),
            headers={"User-Agent": "Raahi-college-demo/1.0 (student major project)"})
        answer = json.load(urllib.request.urlopen(request, timeout=200))
    rows = build(answer["elements"])
    with gzip.open(OUT, "wt", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{len(rows):,} places -> {OUT} ({OUT.stat().st_size / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
