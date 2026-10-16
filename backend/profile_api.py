"""Where does the latency actually go? Measure, do not guess."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_pipeline"))

import numpy as np
import pandas as pd

from engine import PricingEngine
from schemas import PredictRequest

req = PredictRequest(
    product_id="SKU-MINI-CAB", hour=18, day_of_week=2, month=4,
    temperature=28.0, precipitation=0.0, weather_condition="Clear",
    competitor_1_price=180.0, competitor_2_price=188.0, competitor_3_price=176.0,
)

t0 = time.perf_counter()
eng = PricingEngine()
print(f"engine load (once, at startup) : {(time.perf_counter() - t0) * 1000:7.1f} ms\n")


def bench(label, fn, n=30):
    fn()  # warm
    t = time.perf_counter()
    for _ in range(n):
        fn()
    ms = (time.perf_counter() - t) / n * 1000
    print(f"{label:<42}{ms:7.2f} ms")
    return ms


ctx = eng.build_context(req)
grid = np.linspace(20, 32, 121)

print("PER-REQUEST BREAKDOWN")
print("-" * 52)
bench("build_context", lambda: eng.build_context(req))
bench("predict_demand (one batched call)", lambda: eng.predict_demand(ctx, grid))
print("-" * 52)
total = bench("FULL recommend()  <-- what the UI waits on", lambda: eng.recommend(req))

print()
print(f"Was 58.8 ms (three separate model calls: grid, current price, elasticity).")
print(f"Now {total:.1f} ms (one batched call; elasticity read off the curve).")
print(f"Speedup: {58.8 / total:.1f}x")
