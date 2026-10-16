"""End-to-end API test. Run: python backend/test_api.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_pipeline"))

from fastapi.testclient import TestClient

from main import app

BASE = {
    "product_id": "SKU-MINI-CAB",
    "hour": 18, "day_of_week": 2, "month": 4, "is_holiday": False,
    "temperature": 28.0, "precipitation": 0.0, "weather_condition": "Clear",
    # Prices are in INR (₹). SKU-MINI-CAB fares sit around ₹180.
    "competitor_1_price": 180.0, "competitor_2_price": 188.0, "competitor_3_price": 176.0,
}

with TestClient(app) as c:
    print("=" * 78)
    print("HEALTH / PRODUCTS / METRICS")
    print("=" * 78)
    assert c.get("/health/").status_code == 200
    print("  /health/   ", c.get("/health/").json())
    print("  /products/ ", [p["product_id"] for p in c.get("/products/").json()])

    m = c.get("/metrics/").json()
    print(f"  /metrics/   model={m['selected_model']}  R2={m['r2']:.4f}  "
          f"RMSE={m['rmse']:.2f}")
    print(f"              elasticity={m['price_elasticity']:.2f} vs "
          f"truth={m['true_elasticity']:.2f} (err {m['elasticity_recovery_error']:.2f})")

    print()
    print("=" * 78)
    print("SCENARIOS — does context actually move the price?")
    print("=" * 78)
    print(f"  {'scenario':<34}{'price':>8}{'chg':>8}{'demand':>9}"
          f"{'elast':>8}{'profit+':>9}")
    print("  " + "-" * 74)

    scenarios = {
        "Baseline (dry, 6pm, weekday)": {},
        "STORM (heavy rain)": {"precipitation": 12.0, "weather_condition": "Stormy"},
        "Off-peak (3am, dry)": {"hour": 3},
        "Competitors +15%": {"competitor_1_price": 207.0, "competitor_2_price": 216.2,
                             "competitor_3_price": 202.4},
        "Competitors -15%": {"competitor_1_price": 153.0, "competitor_2_price": 159.8,
                             "competitor_3_price": 149.6},
        "Holiday rush + rain": {"is_holiday": True, "precipitation": 8.0,
                                "weather_condition": "Rainy"},
        "Freezing (2C)": {"temperature": 2.0},
    }
    for label, override in scenarios.items():
        r = c.post("/predict/", json={**BASE, **override})
        assert r.status_code == 200, r.text
        d = r.json()
        print(f"  {label:<34}{d['recommended_price']:>8.2f}"
              f"{d['price_change_pct']:>7.1f}%{d['recommended_demand']:>9.1f}"
              f"{d['elasticity']:>8.2f}{d['profit_lift_pct']:>8.1f}%")

    print()
    print("=" * 78)
    print("OBJECTIVE: profit vs revenue")
    print("=" * 78)
    for obj in ["profit", "revenue"]:
        d = c.post("/predict/", json={**BASE, "objective": obj}).json()
        print(f"  {obj:<9} -> price {d['recommended_price']:.2f} "
              f"({d['price_change_pct']:+.1f}%)  guardrail_hit={d['guardrail_hit']}")
        if d["warning"]:
            print(f"            warning: {d['warning'][:90]}...")

    print()
    print("=" * 78)
    print("ERROR HANDLING — bad input must be REJECTED, not silently extrapolated")
    print("=" * 78)
    bad = [
        ("hour = 99",             {**BASE, "hour": 99},                        422),
        ("negative price",        {**BASE, "current_price": -5},               422),
        ("unknown SKU",           {**BASE, "product_id": "SKU-DOES-NOT-EXIST"}, 404),
        ("cost above price",      {**BASE, "current_price": 150, "unit_cost": 170}, 422),
        ("negative rainfall",     {**BASE, "precipitation": -3},               422),
        ("bad weather enum",      {**BASE, "weather_condition": "Sunny"},      422),
        ("missing competitor",    {k: v for k, v in BASE.items()
                                   if k != "competitor_1_price"},              422),
    ]
    ok = True
    for label, payload, expected in bad:
        got = c.post("/predict/", json=payload).status_code
        mark = "PASS" if got == expected else "FAIL"
        ok &= got == expected
        print(f"  {label:<22} expected {expected} -> got {got}   [{mark}]")

    print()
    print("ALL TESTS PASSED" if ok else "SOME TESTS FAILED")
    sys.exit(0 if ok else 1)
