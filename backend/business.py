"""
The business model of one ride: where each rupee of the fare goes.

    Rider pays the fare (GST included)
      - GST, paid to the government
      = Net fare
      - Platform commission  -> Raahi's revenue
      = Driver payout         -> minus the driver's fuel = driver's take-home

    Raahi's profit = commission - payment processing - per-trip insurance - operations

Every number below is a DEMO ASSUMPTION an admin can edit, not a published tariff or real
company accounts. The assumptions in force are saved with each ride when it is booked, so
editing them later changes new rides only and never rewrites the books for old ones.
"""
from fares import VEHICLES

DEFAULT_ASSUMPTIONS = {
    "gst_pct": 5.0,                  # GST on passenger transport via an aggregator
    "payment_pct": 2.0,              # payment gateway fee on the fare
    "insurance_per_ride": 2.0,       # per-trip accident cover for rider and driver
    "ops_per_ride": 3.0,             # support, maps, servers, marketing, spread per ride
    "pickup_km": 1.5,                # driver's empty drive to the pickup
    "commission_pct": {"bike": 15.0, "erickshaw": 10.0, "auto": 12.0, "cab": 20.0, "shared": 20.0},
    # Driver's fuel or charging cost per km. Shared cabs are priced per seat, so their
    # cost is per seat too (a cab's ~₹7.5/km over about three filled seats).
    "fuel_per_km": {"bike": 2.5, "erickshaw": 0.8, "auto": 3.5, "cab": 7.5, "shared": 2.5},
}

LIMITS = {
    "gst_pct": (0, 28), "payment_pct": (0, 10), "insurance_per_ride": (0, 100),
    "ops_per_ride": (0, 200), "pickup_km": (0, 20), "commission_pct": (0, 50), "fuel_per_km": (0, 50),
}


def merge(saved: dict | None) -> dict:
    """Saved assumptions over the defaults, so a new field never breaks an old setting."""
    out = {**DEFAULT_ASSUMPTIONS, **(saved or {})}
    for key in ("commission_pct", "fuel_per_km"):
        out[key] = {**DEFAULT_ASSUMPTIONS[key], **((saved or {}).get(key) or {})}
    return out


def validate(values: dict) -> dict:
    clean = merge(values)
    for key, (low, high) in LIMITS.items():
        items = clean[key].items() if isinstance(clean[key], dict) else [(None, clean[key])]
        for vehicle, value in items:
            if vehicle is not None and vehicle not in VEHICLES:
                raise ValueError(f"Unknown vehicle: {vehicle}")
            if not isinstance(value, (int, float)) or not low <= value <= high:
                name = key.replace("_", " ") + (f" ({vehicle})" if vehicle else "")
                raise ValueError(f"{name} must be between {low} and {high}.")
    return clean


def ride_economics(fare: float, km: float, vehicle: str, normal_fare: float | None,
                   assumptions: dict) -> dict:
    a = merge(assumptions)
    gst = fare * a["gst_pct"] / (100 + a["gst_pct"])
    net_fare = fare - gst
    commission = net_fare * a["commission_pct"][vehicle] / 100
    driver_payout = net_fare - commission
    driver_fuel = (km + a["pickup_km"]) * a["fuel_per_km"][vehicle]
    payment_fee = fare * a["payment_pct"] / 100
    platform_costs = payment_fee + a["insurance_per_ride"] + a["ops_per_ride"]
    profit = commission - platform_costs
    r = lambda x: round(x, 2)
    return {
        "fare": r(fare), "gst": r(gst), "net_fare": r(net_fare),
        "commission_pct": a["commission_pct"][vehicle], "commission": r(commission),
        "driver_payout": r(driver_payout), "driver_fuel": r(driver_fuel),
        "driver_net": r(driver_payout - driver_fuel),
        "payment_fee": r(payment_fee), "insurance": r(a["insurance_per_ride"]), "ops": r(a["ops_per_ride"]),
        "platform_costs": r(platform_costs), "profit": r(profit),
        "margin_pct": r(profit / fare * 100) if fare else 0.0,
        # What dynamic pricing added (or took off) compared with the plain fare card.
        "pricing_effect": r(fare - normal_fare) if normal_fare is not None else 0.0,
    }


SUM_KEYS = ("fare", "gst", "commission", "driver_payout", "driver_fuel", "driver_net",
            "payment_fee", "insurance", "ops", "platform_costs", "profit", "pricing_effect")


def summarise(rows: list) -> dict:
    """Totals and per-ride averages over a list of ride_economics results."""
    totals = {k: round(sum(e[k] for e in rows), 2) for k in SUM_KEYS}
    n = len(rows)
    totals["rides"] = n
    totals["avg_profit"] = round(totals["profit"] / n, 2) if n else 0.0
    totals["avg_fare"] = round(totals["fare"] / n, 2) if n else 0.0
    totals["margin_pct"] = round(totals["profit"] / totals["fare"] * 100, 2) if totals["fare"] else 0.0
    totals["loss_rides"] = sum(1 for e in rows if e["profit"] < 0)
    return totals
