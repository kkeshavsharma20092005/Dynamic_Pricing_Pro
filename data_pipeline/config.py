"""Single source of truth for constants shared across the pipeline and the API."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"
OUTPUT_DIR = ROOT / "outputs"

for _d in (DATA_DIR, MODEL_DIR, OUTPUT_DIR):
    _d.mkdir(exist_ok=True)

RAW_CSV = DATA_DIR / "pricing_data.csv"
MODEL_PKL = MODEL_DIR / "pricing_model.pkl"
METRICS_JSON = OUTPUT_DIR / "metrics.json"
GROUND_TRUTH_JSON = OUTPUT_DIR / "ground_truth.json"

SEED = 42
TARGET = "units_sold"

# ---------------------------------------------------------------------------
# GROUND TRUTH. The generator uses these to build demand; the model never sees
# them. evaluate.py checks whether the fitted model RECOVERS them. That check is
# the entire justification for using synthetic data instead of real data: with
# real data you can never know if your elasticity estimate is correct.
# ---------------------------------------------------------------------------
# Elasticity is NOT one number. It varies with context, and that variation is the
# entire reason dynamic pricing beats a fixed price. A commuter in the rain at 6pm
# barely glances at price; a browser on a dry Sunday shops around. So the true
# elasticity of a row is:
#
#   e_i = BASE + RUSH_SHIFT * rush_intensity + RAIN_SHIFT * is_raining
#
# Both shifts are POSITIVE, i.e. they push elasticity toward zero (less sensitive)
# exactly when the customer needs the product most. That is the surge opportunity,
# and a model that cannot see it cannot price dynamically.
TRUE_BASE_ELASTICITY = -2.10
TRUE_RUSH_ELASTICITY_SHIFT = 0.55   # per unit of rush_intensity
TRUE_RAIN_ELASTICITY_SHIFT = 0.30   # when it is raining

# Headline figure quoted in the docs: the demand-weighted average of the above.
# Computed exactly by generate_data.py and written to ground_truth.json.
TRUE_OWN_ELASTICITY = -1.80    # approximate mean; the generator reports the exact value
TRUE_CROSS_ELASTICITY = 0.90   # 1% competitor price rise -> 0.9% demand gain

# A synthetic INDIAN RIDE-HAILING market. Every monetary figure is in Indian Rupees
# (INR, ₹). The catalogue is five vehicle tiers a commuter can book in an Indian
# metro, from a bike taxi to a full-size SUV, priced natively in rupees.
#
#   base_price  : the fair-weather, off-peak fare the surge engine anchors to (₹)
#   base_demand : rides per hour at that fare in average conditions
#   cost        : driver payout + fuel per ride (₹) - the floor the optimiser may never cross
# Cheaper tiers are higher volume; premium tiers are scarcer but carry a fatter margin.
PRODUCTS = {
    "SKU-BIKE-TAXI":     {"base_price": 60.0,  "base_demand": 55.0, "cost": 28.0},
    "SKU-AUTO-RICKSHAW": {"base_price": 90.0,  "base_demand": 48.0, "cost": 42.0},
    "SKU-MINI-CAB":      {"base_price": 180.0, "base_demand": 34.0, "cost": 95.0},
    "SKU-PRIME-SEDAN":   {"base_price": 320.0, "base_demand": 20.0, "cost": 175.0},
    "SKU-SUV-XL":        {"base_price": 520.0, "base_demand": 12.0, "cost": 300.0},
}

WEATHER_CONDITIONS = ["Clear", "Cloudy", "Rainy", "Stormy"]

START = "2024-01-01"
HOURS = 2920          # ~4 months of hourly data per SKU (Jan 1 - May 1, 2024)
# 5 SKUs x 2920 hours = 14,600 rows, comfortably over the 5,000 minimum.
