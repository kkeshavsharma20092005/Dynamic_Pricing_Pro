"""
Address search through OpenStreetMap's public Nominatim service.

Its usage policy asks for an identifying User-Agent, at most one request a second, and no
search-as-you-type, so searches run on submit, one at a time, and answers are cached. Each
search sends the typed address to that service.

A bad pin is worse than no pin. Nominatim answers "Bharat Nagar, Jammu" with Jammu Airport,
so a result is kept only if it really contains the words that were asked for.
"""
import asyncio
import re
import time

import httpx

from chatbot import normalise
from localities import CITY_WORDS
from places import distance_km, in_service_area

URL = "https://nominatim.openstreetmap.org"
HEADERS = {"User-Agent": "Raahi-college-demo/1.0 (student major project)"}
MIN_INTERVAL = 1.1
VIEWBOX = "73.7,34.9,76.0,32.2"      # west, north, east, south of J&K
TIMEOUT = 6.0
FILLER = {"near", "road", "lane", "gali", "mohalla", "colony", "house", "no", "number", "the", "opposite", "opp"}

_lock = asyncio.Lock()
_last_call = 0.0
_cache: dict = {}

CONSONANTS = dict(zip("कखगघङचछजझञटठडढणतथदधनपफबभमयरलवशषसह",
                      "k kh g gh n ch chh j jh n t th d dh n t th d dh n p ph b bh m y r l v sh sh s h".split()))
VOWELS = {"अ": "a", "आ": "a", "इ": "i", "ई": "i", "उ": "u", "ऊ": "u", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au"}
MATRAS = {"ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "े": "e", "ै": "ai", "ो": "o", "ौ": "au"}


def transliterate(word: str) -> str:
    """Devanagari to Latin letters, good enough to search map names spelled in English."""
    out = []
    for i, ch in enumerate(word):
        if ch in CONSONANTS:
            out.append(CONSONANTS[ch])
            following = word[i + 1] if i + 1 < len(word) else ""
            if following and following not in MATRAS and following != "्" and following not in "ंँ":
                out.append("a")
        elif ch in VOWELS:
            out.append(VOWELS[ch])
        elif ch in MATRAS:
            out.append(MATRAS[ch])
        elif ch in "ंँ":
            out.append("n")
    return "".join(out)


def search_forms(text: str) -> list:
    """Ways to spell a query for the map. Urdu script has no reliable Latin form, so none."""
    if re.search(r"[؀-ۿ]", text):
        return []
    if re.search(r"[ऀ-ॿ]", text):
        latin = " ".join(transliterate(t) for t in normalise(text))
        return [latin, latin.replace("u", "oo")] if "u" in latin else [latin]
    return [text]


def important_words(text: str) -> list:
    return [t for t in normalise(text) if len(t) >= 3 and t not in CITY_WORDS and t not in FILLER]


def is_genuine_match(words: list, display_name: str) -> bool:
    display = display_name.lower()
    return bool(words) and all(w in display for w in words)


async def _fetch(path: str, params: dict):
    """One polite request. None if the service can't be reached."""
    global _last_call
    async with _lock:
        wait = MIN_INTERVAL - (time.monotonic() - _last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
                response = await client.get(f"{URL}/{path}", params={"format": "jsonv2", "accept-language": "en", **params})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            return None


async def search(text: str, near: dict | None = None) -> list:
    """Genuine J&K matches for an address, closest to `near` first."""
    key = text.strip().lower()
    if key in _cache:
        results = _cache[key]
    else:
        results = []
        unreachable = False
        for form in search_forms(text):
            found = await _fetch("search", {"q": form, "limit": 6, "countrycodes": "in", "viewbox": VIEWBOX, "bounded": 1})
            if found is None:
                unreachable = True
                break
            words = important_words(form)
            for r in found:
                lat, lon = float(r["lat"]), float(r["lon"])
                if is_genuine_match(words, r["display_name"]) and in_service_area(lat, lon):
                    results.append({"lat": lat, "lon": lon, "name": text.strip().title() if form == text else r["display_name"].split(",")[0],
                                    "detail": r["display_name"][:110], "approx": False})
            if results:
                break
        if not unreachable:
            _cache[key] = results
    if near:
        results = sorted(results, key=lambda r: distance_km(near["lat"], near["lon"], r["lat"], r["lon"]))
    return results


async def describe(lat: float, lon: float) -> str | None:
    """A short name for a coordinate, such as the road and area the rider is standing on."""
    found = await _fetch("reverse", {"lat": lat, "lon": lon, "zoom": 17})
    if not found or "error" in found:
        return None
    address = found.get("address", {})
    parts = [address.get(k) for k in ("road", "neighbourhood", "suburb", "village", "town", "city")]
    unique = list(dict.fromkeys(p for p in parts if p))
    return ", ".join(unique[:3]) or None
