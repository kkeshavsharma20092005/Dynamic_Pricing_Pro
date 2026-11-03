"""
Turn a trip into a fare: a distance fare, times the pricing engine's multiplier for the
current conditions, limited by a fair-price cap, with a plain-language reason for it.

The multiplier comes from the demand model's profit optimum, which has no sense of
fairness: snow makes customers less price-sensitive, so left alone it charges most when
people have the fewest alternatives. The cap is the deliberate business rule on top.
"""
from datetime import datetime
from math import pi, sin

from config import PRODUCTS, REGIONS
from schemas import PredictRequest
from season import FIXED_HOLIDAYS, active_pilgrimage, pilgrim_index, tourist_index

# Fare-card values are demo assumptions, not published J&K tariffs.
VEHICLES = {
    "bike":      {"label": "Bike", "seats": 1, "base": 20, "per_km": 8, "max_km": 60},
    "erickshaw": {"label": "E-rickshaw", "seats": 3, "base": 10, "per_km": 10, "max_km": 12},
    "auto":      {"label": "Auto", "seats": 3, "base": 30, "per_km": 14, "max_km": 40},
    "cab":       {"label": "Cab", "seats": 4, "base": 60, "per_km": 20, "max_km": None},
    "shared":    {"label": "Shared cab (per seat)", "seats": 1, "base": 30, "per_km": 6, "max_km": None},
}

ENGINE_MAX_CHANGE_PCT = 40.0
MIN_EFFECT_RUPEES = 1

# ASSUMED rate cards. No current J&K rates were found for either company, and neither
# offers an open fare feed, so these are placeholders an admin can edit. They are NOT
# Rapido or Uber prices. The app shows them only as a labelled range, and links out for
# the real fare.
DEFAULT_RIVAL_RATES = {
    "rapido": {"label": "Rapido", "url": "https://www.rapido.bike/",
               "cards": {"bike": {"base": 25, "per_km": 7}, "auto": {"base": 30, "per_km": 13},
                         "cab": {"base": 60, "per_km": 17}}},
    "uber": {"label": "Uber", "url": "https://m.uber.com/",
             "cards": {"bike": {"base": 25, "per_km": 8}, "auto": {"base": 35, "per_km": 14},
                       "cab": {"base": 70, "per_km": 19}}},
}
RIVAL_MAX_KM = 60            # assumed: these estimates cover local trips only
RIVAL_RANGE = 0.15           # shown as +/-15%, since the true rate and any surge are unknown
RIVAL_RATIO_LIMITS = (0.85, 1.15)   # the range of rival prices the model trained on


def rival_estimates(vehicle: str, km: float, rates: dict) -> list:
    if km > RIVAL_MAX_KM:
        return []
    estimates = []
    for key, rival in rates.items():
        card = rival["cards"].get(vehicle)
        if card:
            mid = card["base"] + card["per_km"] * km
            estimates.append({"id": key, "label": rival["label"], "url": rival["url"],
                              "low": round(mid * (1 - RIVAL_RANGE)), "high": round(mid * (1 + RIVAL_RANGE)),
                              "mid": round(mid)})
    return estimates


def recommend_choice(our_fare: int, rivals: list) -> dict:
    """Say which to pick. It only names a rival when the whole estimate range is lower."""
    if not rivals:
        return {"pick": "raahi", "confident": False,
                "message": "No rival estimate for this trip, so there is nothing to compare."}
    cheaper = [r for r in rivals if r["high"] < our_fare]
    if cheaper:
        best = min(cheaper, key=lambda r: r["mid"])
        return {"pick": best["id"], "confident": True,
                "message": f"{best['label']} looks cheaper by estimate. Check its app for the real fare before you book."}
    if all(our_fare < r["low"] for r in rivals):
        return {"pick": "raahi", "confident": True,
                "message": "Raahi is the best price here, below every estimate."}
    return {"pick": "raahi", "confident": False,
            "message": "Too close to call on estimates. Raahi's fare is confirmed now; the others are not."}


def default_conditions(region: str, month: int) -> dict:
    """Seasonal normal weather until an admin reports something specific."""
    spec = REGIONS[region]
    temp = spec["temp_mean"] + spec["temp_season"] * sin(2 * pi * ((month - 0.5) * 30.4 - 105) / 365.25)
    return {"temperature": round(temp, 1), "precipitation": 0.0, "weather_condition": "Clear",
            "road_closed": False, "pilgrim_override": None, "hour_override": None}


def is_hardship(conditions: dict) -> bool:
    return bool(conditions["road_closed"]) or conditions["weather_condition"] in ("Stormy", "Snowy")


def _rival_prices(base: float, normal_fare: float, rivals: list) -> list:
    """Rival estimates as engine inputs, kept inside the range the model has seen."""
    low, high = RIVAL_RATIO_LIMITS
    prices = [base * min(max(r["mid"] / normal_fare, low), high) for r in rivals[:2]]
    return prices + [base, base * 1.05][len(prices):]


def _engine_request(product_id, when: datetime, conditions: dict, **override) -> PredictRequest:
    spec = PRODUCTS[product_id]
    region, base = spec["region"], spec["base_price"]
    doy = when.timetuple().tm_yday
    pilgrim = conditions["pilgrim_override"]
    hour = conditions["hour_override"]
    values = {
        "product_id": product_id,
        "hour": when.hour if hour is None else hour,
        "day_of_week": when.weekday(),
        "month": when.month,
        "is_holiday": (when.month, when.day) in FIXED_HOLIDAYS,
        "temperature": conditions["temperature"],
        "precipitation": conditions["precipitation"],
        "weather_condition": conditions["weather_condition"],
        "road_closed": conditions["road_closed"],
        "pilgrim_index": float(pilgrim_index(region, doy)) if pilgrim is None else pilgrim,
        "tourist_index": float(tourist_index(region, when.month)),
        # Replaced by rival estimates when the trip has them.
        "competitor_1_price": base, "competitor_2_price": base * 1.05, "competitor_3_price": base * 0.97,
        "current_price": base,
        "max_change_pct": ENGINE_MAX_CHANGE_PCT,
    }
    values.update(override)
    return PredictRequest(**values)


def _multiplier(engine, request: PredictRequest) -> float:
    result = engine.recommend(request)
    return result["recommended_price"] / result["current_price"]


def _counterfactuals(request: PredictRequest, region: str, doy: int) -> list:
    """What each active condition would look like if it were switched off."""
    factors = []
    if request.hour in (7, 8, 9, 17, 18, 19, 20):
        factors.append(("Rush hour", {"hour": 14}))
    if request.weather_condition.value == "Snowy":
        factors.append(("Snowfall", {"precipitation": 0.0, "weather_condition": "Clear"}))
    elif request.precipitation > 0.1:
        factors.append(("Rain", {"precipitation": 0.0, "weather_condition": "Clear"}))
    if request.road_closed:
        factors.append(("Road closure", {"road_closed": False}))
    if request.pilgrim_index > 0:
        name = active_pilgrimage(region, doy) or "Yatra"
        factors.append((f"{name} crowds", {"pilgrim_index": 0.0}))
    if request.tourist_index >= 0.6:
        factors.append(("Tourist season", {"tourist_index": 0.2}))
    if request.is_holiday:
        factors.append(("Festival or holiday", {"is_holiday": False}))
    if request.day_of_week >= 5:
        factors.append(("Weekend", {"day_of_week": 2}))
    return factors


def price_option(engine, vehicle: str, region: str, km: float, when: datetime,
                 conditions: dict, caps: dict, rival_rates: dict = DEFAULT_RIVAL_RATES) -> dict:
    card = VEHICLES[vehicle]
    product_id = f"{region}-{vehicle.upper()}"
    normal_fare = card["base"] + card["per_km"] * km

    # Rival prices move demand, so they are part of finding the best fare.
    rivals = rival_estimates(vehicle, km, rival_rates)
    base = PRODUCTS[product_id]["base_price"]
    first, second = _rival_prices(base, normal_fare, rivals)
    market = {"competitor_1_price": first, "competitor_2_price": second}

    request = _engine_request(product_id, when, conditions, **market)
    model_multiplier = _multiplier(engine, request)

    hardship = is_hardship(conditions)
    cap = caps["hardship"] if hardship else caps["normal"]
    multiplier = min(model_multiplier, cap)
    capped = model_multiplier > cap + 1e-9

    # Leave-one-out: re-price with each condition removed and report the difference. The
    # effects overlap, so they are reasons with a size and need not sum to the total.
    # Measured before the cap, or a capped snowfall fare would show snow as having no
    # effect. The cap is reported separately, as saved_by_cap.
    reasons = []
    doy = when.timetuple().tm_yday
    factors = _counterfactuals(request, region, doy)
    if rivals:
        factors.append(("Rival fares", {"competitor_1_price": base, "competitor_2_price": base * 1.05}))
    for label, override in factors:
        without = _multiplier(engine, _engine_request(product_id, when, conditions, **{**market, **override}))
        effect = round((model_multiplier - without) * normal_fare)
        if abs(effect) >= MIN_EFFECT_RUPEES:
            reasons.append({"factor": label, "effect": effect})
    reasons.sort(key=lambda r: -abs(r["effect"]))

    return {
        "vehicle": vehicle,
        "label": card["label"],
        "seats": card["seats"],
        "product_id": product_id,
        "normal_fare": round(normal_fare),
        "fare": round(normal_fare * multiplier),
        "multiplier": round(multiplier, 2),
        "model_multiplier": round(model_multiplier, 2),
        "fair_cap": cap,
        "fair_capped": capped,
        "saved_by_cap": round((model_multiplier - multiplier) * normal_fare) if capped else 0,
        "reasons": reasons,
        "rivals": rivals,
        "recommendation": recommend_choice(round(normal_fare * multiplier), rivals),
    }


def available_vehicles(region: str, km: float, crosses_regions: bool) -> list:
    sold_here = [s["vehicle"] for s in PRODUCTS.values() if s["region"] == region]
    usable = []
    for vehicle in sold_here:
        limit = VEHICLES[vehicle]["max_km"]
        if limit is not None and km > limit:
            continue
        if crosses_regions and vehicle not in ("cab", "shared"):
            continue
        usable.append(vehicle)
    return usable
