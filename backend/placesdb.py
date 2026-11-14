"""
Find any named place in J&K from however a rider says or spells it.

People write "bawe wali maat", "बावे वाली माता" and "باوے والی ماتا" for the same temple, so
each word is reduced to its consonants, which survive spelling, script and speech-to-text.
The map data (see data_pipeline/build_places.py) is searched in memory: no network, no cost.
"""
import gzip
import json
import re
from difflib import SequenceMatcher

from chatbot import normalise
from config import DATA_DIR
from geocode import transliterate
from localities import CITY_WORDS, LOCALITIES
from places import distance_km, nearest_place, set_coverage

DATA_FILE = DATA_DIR / "jk_places.json.gz"
GENERIC = {t for w in ("mandir temple shrine masjid mosque dargah gurudwara ziyarat church mandi "
                       "मंदिर मस्जिद दरगाह गुरुद्वारा مندر مسجد درگاہ زیارت گردوارہ").split() for t in normalise(w)}
RANK = {"city": 8, "town": 7, "suburb": 5, "neighbourhood": 5, "quarter": 5, "worship": 5, "tourism": 5, "historic": 5,
        "railway": 5, "aeroway": 6, "hospital": 4, "college": 3, "university": 4, "bus_station": 4, "village": 3,
        "locality": 3, "natural": 3, "leisure": 3, "hamlet": 1, "school": 0,
        "mall": 4, "marketplace": 4, "bus_stop": 4, "fuel": 3, "police": 3, "bank": 2, "clinic": 2, "hotel": 3,
        "road": 3, "post_office": 2, "courthouse": 3, "townhall": 3, "cinema": 3, "pharmacy": 1, "restaurant": 1,
        "cafe": 1, "shop": 1, "office": 1, "atm": 0, "doctors": 1, "dentist": 0, "landmark": 1, "amenity": 1,
        "isolated_dwelling": 0}
LABELS = {"worship": "Temple or shrine", "city": "City", "town": "Town", "village": "Village", "hamlet": "Hamlet",
          "hospital": "Hospital", "college": "College", "university": "University", "school": "School",
          "railway": "Railway station", "aeroway": "Airport", "bus_station": "Bus stand", "tourism": "Tourist spot",
          "historic": "Historic place", "natural": "Natural landmark", "leisure": "Park",
          "mall": "Mall", "shop": "Shop", "marketplace": "Market", "bus_stop": "Bus stop", "fuel": "Petrol pump",
          "police": "Police station", "bank": "Bank", "atm": "ATM", "clinic": "Clinic", "doctors": "Clinic",
          "dentist": "Dental clinic", "pharmacy": "Chemist", "hotel": "Hotel", "restaurant": "Restaurant",
          "cafe": "Cafe", "road": "Road", "office": "Office", "post_office": "Post office", "courthouse": "Court",
          "townhall": "Town hall", "cinema": "Cinema", "library": "Library", "kindergarten": "School",
          "isolated_dwelling": "Settlement", "locality": "Locality", "suburb": "Area", "neighbourhood": "Area",
          "quarter": "Area", "landmark": "Landmark", "amenity": "Landmark"}
# Short names riders use for institutions whose map name is long. Only places in the data.
SHORT_NAMES = {
    "Indian Institute of Technology Jammu": ["iit jammu", "iit", "आईआईटी जम्मू", "आईआईटी"],
    "Model Institute of Engineering and Technology": ["miet jammu", "miet", "एमआईईटी"],
    "University of Jammu": ["jammu university", "ju jammu"],
    "Shri Mata Vaishno Devi University": ["smvdu", "vaishno devi university", "katra university"],
    "Govt Gandhi Memorial Science College": ["ggm science college", "ggm college", "science college jammu"],
    "National Institute of Technology, Srinagar": ["nit srinagar"],
    "Sher-e-Kashmir University of Agricultural Sciences and Technology of Kashmir": ["skuast kashmir", "skuast"],
}
# Kinds that name where a place is: a result is labelled with the nearest of these.
SETTLEMENT_KINDS = {"city", "town", "suburb", "neighbourhood", "quarter", "village", "locality"}
URDU_SOUNDS = str.maketrans({
    "ب": "b", "پ": "p", "ت": "t", "ٹ": "t", "ث": "s", "ج": "j", "چ": "c", "خ": "k", "د": "d", "ڈ": "d", "ذ": "z",
    "ر": "r", "ڑ": "r", "ز": "z", "ژ": "z", "س": "s", "ش": "s", "ص": "s", "ض": "z", "ط": "t", "ظ": "z", "ف": "f",
    "ق": "k", "ک": "k", "گ": "g", "ل": "l", "م": "m", "ن": "n", "ں": "n", "و": "w", "ح": "", "ہ": "", "ھ": "", "ھ": "",
    "ا": "", "آ": "", "ع": "", "ء": "", "ئ": "", "ی": "", "ے": ""})

_rows: list = []
_settlements: list = []
_by_sound: dict = {}
_by_word: dict = {}


def latin_sound(word: str) -> str:
    """"bawe" and "bave" -> "bw"; "maat" and "mata" -> "mt"; "bharat" and "barat" -> "brt"."""
    w = word.lower()
    for a, b in (("ph", "f"), ("v", "w"), ("q", "k"), ("x", "ks"), ("ck", "k"), ("chh", "c"), ("ch", "c"), ("sh", "s")):
        w = w.replace(a, b)
    w = re.sub(r"[aeiouyh]", "", w)
    return re.sub(r"(.)\1+", r"\1", w)


def sounds_of(token: str) -> set:
    """Every consonant form of a word. Urdu's و can be a consonant or a vowel, so it gets both."""
    if re.search(r"[ऀ-ॿ]", token):
        return {latin_sound(transliterate(token))} - {""}
    if re.search(r"[؀-ۿ]", token):
        spoken = re.sub(r"(.)\1+", r"\1", token.translate(URDU_SOUNDS))
        return {spoken, spoken.replace("w", "")} - {""}
    return {latin_sound(token)} - {""}


def _load():
    rows = json.loads(gzip.open(DATA_FILE, "rt", encoding="utf-8").read()) if DATA_FILE.exists() else []
    rows += [[f"{name}, {city}", lat, lon, "neighbourhood", aliases] for name, city, lat, lon, aliases in LOCALITIES]
    for i, (name, lat, lon, kind, others) in enumerate(rows):
        words = [t for t in normalise(name) if t not in CITY_WORDS or len(normalise(name)) == 1]
        forms = [words] + [normalise(o) for o in list(others) + SHORT_NAMES.get(name, [])]
        _rows.append({"name": name, "lat": lat, "lon": lon, "kind": kind, "forms": forms})
        if kind in SETTLEMENT_KINDS:
            _settlements.append(_rows[-1])
        for form in forms:
            for token in form:
                _by_word.setdefault(token, set()).add(i)
                for sound in sounds_of(token):
                    _by_sound.setdefault(sound, set()).add(i)
    set_coverage({(round(lat * 10), round(lon * 10)) for _, lat, lon, _, _ in rows})


def _candidates(token: str, strict: bool) -> tuple:
    """(exact matches, sound-alike matches). A one-consonant sound is too weak to trust."""
    exact = _by_word.get(token, set())
    sounds = set()
    for sound in sounds_of(token):
        if len(sound) >= 2:
            sounds |= _by_sound.get(sound, set())
    return exact, sounds


def _near_spelling(token: str, form: list) -> bool:
    return any(SequenceMatcher(None, token, other).ratio() >= 0.7 for other in form)


def search(text: str, near: dict | None = None, strict: bool = False, limit: int = 5) -> list:
    """
    Places matching these words, best first. `strict` is for loose chatter that may not be a
    place at all: it needs a stronger match, and won't allow a misspelt word.
    """
    tokens = [t for t in normalise(text) if t not in CITY_WORDS]
    required = [t for t in tokens if t not in GENERIC] or tokens
    if not required:
        return []

    matched = [_candidates(t, strict) for t in required]
    pool = set.intersection(*[a | b for a, b in matched])
    fuzzy = False
    if not pool and len(required) >= 2 and not strict:
        # One misheard word, as in "talab tilon": the others must fix the place first.
        for skip in range(len(required)):
            rest = [a | b for i, (a, b) in enumerate(matched) if i != skip]
            for i in set.intersection(*rest):
                if any(_near_spelling(required[skip], form) for form in _rows[i]["forms"]):
                    pool.add(i)
        fuzzy = bool(pool)
    if strict and len(required) == 1 and len(next(iter(sounds_of(required[0])), "")) < 3 and required[0] not in _by_word:
        return []

    results = []
    for i in pool:
        row = _rows[i]
        # Judge a place only by the names that contain these words, not its unrelated aliases.
        relevant = [form for form in row["forms"] if any(t in form or sounds_of(t) & {x for w in form for x in sounds_of(w)} for t in required)]
        best_extra = min(len([t for t in form if t not in GENERIC]) - len(required) for form in relevant or row["forms"])
        exact_words = sum(1 for t, (a, _) in zip(required, matched) if i in a)
        score = 4 * exact_words - 2 * max(best_extra, 0) + RANK.get(row["kind"], 2) + (0 if fuzzy else 3)
        if any([t for t in form if t not in GENERIC] == required for form in row["forms"]):
            score += 6
        away = distance_km(near["lat"], near["lon"], row["lat"], row["lon"]) if near else 0
        results.append((score - min(away / 25, 6), exact_words, row))
    results.sort(key=lambda r: -r[0])
    # When some place has every word exactly, sound-alikes are noise: "iit jammu" is IIT Jammu,
    # not a mosque whose name merely sounds a little like it.
    if any(exact == len(required) for _, exact, _ in results):
        results = [r for r in results if r[1] == len(required)]

    unique = []
    for score, exact, row in results:
        if any(u["name"] == row["name"] and distance_km(u["lat"], u["lon"], row["lat"], row["lon"]) < 1 for u in unique):
            continue
        town = area_label(row["lat"], row["lon"], row["name"])
        unique.append({"lat": row["lat"], "lon": row["lon"], "name": row["name"], "score": round(score, 1),
                       "kind": row["kind"], "town": town, "approx": False, "exact": exact == len(required),
                       "detail": f"{LABELS.get(row['kind'], 'Place')} · {town}"})
        if len(unique) == limit:
            break
    return unique


def area_label(lat: float, lon: float, own_name: str = "") -> str:
    """Where a place is, in words a local would use: the nearest village, area or town ("near Jagti"),
    or the distance from the nearest well-known place when nothing is close. Never a landmark
    kilometres away, which made IIT Jammu look as if it were at Bahu Fort."""
    best = None
    own = own_name.split(",")[0].lower()
    for row in _settlements:
        name = row["name"].split(",")[0].lower()
        if own and (name.startswith(own) or own.startswith(name)):
            continue
        km = distance_km(lat, lon, row["lat"], row["lon"])
        if best is None or km < best[0]:
            best = (km, row["name"])
    if best and best[0] <= 4:
        return f"near {best[1].split(',')[0]}"
    known = nearest_place(lat, lon)
    km = distance_km(lat, lon, known["lat"], known["lon"])
    return f"near {known['name']}" if km < 1.5 else f"{km:.0f} km from {known['name']}"


def is_clear_winner(results: list) -> bool:
    """False when two equally good places are far apart, so the rider should choose."""
    if len(results) < 2:
        return bool(results)
    first, second = results[0], results[1]
    far = distance_km(first["lat"], first["lon"], second["lat"], second["lon"]) > 3
    return not far or first["score"] - second["score"] >= 2


# Places of worship are one kind in the map data; their names tell the faith apart.
FAITH_WORDS = {
    "mosque": ("masjid", "mosque", "jamia", "مسجد", "मस्जिद"),
    "gurudwara": ("gurdwara", "gurudwara", "گردوارہ", "गुरुद्वारा"),
    "church": ("church", "चर्च"),
    "dargah": ("dargah", "ziyarat", "درگاہ", "زیارت", "दरगाह"),
    "temple": ("temple", "mandir", "mata", "devi", "dham", "shiv", "bhawan", "bhavan", "मंदिर", "माता", "देवी", "धाम", "शिव", "مندر"),
}


def faith_of(row: dict) -> str | None:
    names = " ".join(" ".join(form) for form in row["forms"]) + " " + row["name"].lower()
    for faith, words in FAITH_WORDS.items():          # temple last: "Mata" can appear in other names
        if any(word in names for word in words):
            return faith
    return None


def nearby_worship(lat: float, lon: float, faith: str, limit: int = 6, radius_km: float = 15) -> list:
    """The nearest temples (or mosques, gurudwaras) to a point, closest first, with straight-line km."""
    found = []
    for row in _rows:
        # A bare "Mandir" or "Masjid" on the map can't be told apart from its neighbours.
        if row["kind"] == "worship" and faith_of(row) == faith and set(row["forms"][0]) - GENERIC:
            km = distance_km(lat, lon, row["lat"], row["lon"])
            if km <= radius_km:
                found.append({"name": row["name"], "lat": row["lat"], "lon": row["lon"], "km": round(km, 1)})
    return sorted(found, key=lambda r: r["km"])[:limit]


def find_in_area(text: str, lat: float, lon: float, radius_km: float = 3.0) -> dict | None:
    """The nearest place inside an area whose name has every word said: after "where in Gandhi Nagar?",
    "district hospital" means the one in Gandhi Nagar, not a better-named one 40 km away."""
    words = [w for w in normalise(text) if w not in CITY_WORDS]
    if not words:
        return None
    best = None
    for row in _rows:
        names = [set(form) for form in row["forms"]]
        if any(all(w in form for w in words) for form in names):
            km = distance_km(lat, lon, row["lat"], row["lon"])
            if km <= radius_km and (best is None or km < best[0]):
                best = (km, row)
    return {"name": best[1]["name"], "lat": best[1]["lat"], "lon": best[1]["lon"]} if best else None


# The kinds of place a rider names as "where in Gandhi Nagar": hospitals, markets, colleges...
LANDMARK_WORDS = {"chowk", "station", "fort", "qila", "palace", "mahal", "mandi", "garden", "bagh", "gate", "park", "ground",
                  "चौक", "स्टेशन", "किला", "महल", "मंडी", "बाग", "पार्क"}
SPOT_KINDS = {"hospital", "marketplace", "mall", "college", "university", "bus_station", "railway", "worship",
              "tourism", "historic", "cinema", "leisure", "courthouse", "townhall"}


def spots_in(lat: float, lon: float, radius_km: float, limit: int = 6) -> list:
    """Well-known spots inside an area, best known first and at most two of a kind, for "where in X?"."""
    found = []
    for row in _rows:
        if row["kind"] not in SPOT_KINDS or "closed" in row["name"].lower() or not set(row["forms"][0]) - GENERIC:
            continue
        # "Historic" is mostly statues named after people; keep the ones riders go to.
        if row["kind"] in ("historic", "leisure") and not LANDMARK_WORDS & set(row["forms"][0]):
            continue
        if not re.search(r"[^\W\d_]{3}", row["name"]):         # "15 Corps" and other codes
            continue
        km = distance_km(lat, lon, row["lat"], row["lon"])
        if km <= radius_km:
            found.append((-RANK.get(row["kind"], 0), km, row))
    spots, per_kind, names = [], {}, set()
    for _, km, row in sorted(found, key=lambda f: (f[0], f[1])):
        if per_kind.get(row["kind"], 0) >= 2 or row["name"].lower() in names:
            continue
        per_kind[row["kind"]] = per_kind.get(row["kind"], 0) + 1
        names.add(row["name"].lower())
        spots.append({"name": row["name"], "lat": row["lat"], "lon": row["lon"]})
        if len(spots) == limit:
            break
    return spots


_load()
