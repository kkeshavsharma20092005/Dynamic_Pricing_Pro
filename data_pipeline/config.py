"""Single source of truth for constants shared across the pipeline and the API."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "models"
OUTPUT_DIR = ROOT / "outputs"

for _d in (DATA_DIR, MODEL_DIR, OUTPUT_DIR):
    _d.mkdir(exist_ok=True)

# Gzipped: a year of hourly rows is ~15 MB as plain text, and Excel cannot silently
# rewrite the dates in a .gz.
RAW_CSV = DATA_DIR / "pricing_data.csv.gz"
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
#             + SNOW_SHIFT * is_snowing + PILGRIM_SHIFT * pilgrim_index
#
# Both shifts are POSITIVE, i.e. they push elasticity toward zero (less sensitive)
# exactly when the customer needs the product most. That is the surge opportunity,
# and a model that cannot see it cannot price dynamically.
#
# The shifts are calibrated against the true optimum, P* = cost * e / (1 + e), which
# explodes as e approaches -1. Larger shifts put the optimum at +200% or more in rainy
# rush hours, far beyond any guardrail, so every surge would just report the limit.
# With these values the optimum stays inside the range the prices were sampled from.
TRUE_BASE_ELASTICITY = -2.10
TRUE_RUSH_ELASTICITY_SHIFT = 0.28   # per unit of rush_intensity
TRUE_RAIN_ELASTICITY_SHIFT = 0.14   # when it is raining
TRUE_SNOW_ELASTICITY_SHIFT = 0.10   # extra, when that precipitation falls as snow
TRUE_PILGRIM_ELASTICITY_SHIFT = 0.08  # per unit of pilgrim_index

# The exact mean elasticity is computed by generate_data.py and written to
# ground_truth.json.
TRUE_CROSS_ELASTICITY = 0.90   # 1% competitor price rise -> 0.9% demand gain

# A synthetic JAMMU & KASHMIR RIDE-HAILING market. Every monetary figure is in Indian
# Rupees (INR, ₹). These figures are modelling assumptions, not measured J&K fares.
#
# Three regions with different climate and calendars. Each product is one vehicle type
# sold in one region, because a Jammu e-rickshaw and a Kashmir shared cab do not compete
# for the same customer.
REGIONS = {
    "JMU": {"name": "Jammu plains", "temp_mean": 24.0, "temp_season": 10.5, "temp_daily": 5.0,
            "rain_front_prob": 0.012, "monsoon_factor": 3.0, "winter_factor": 1.5,
            "closure_prone": False, "road_factor": 1.3, "speed_kmph": 28.0},
    "KSH": {"name": "Kashmir valley", "temp_mean": 13.5, "temp_season": 12.0, "temp_daily": 5.5,
            "rain_front_prob": 0.012, "monsoon_factor": 1.2, "winter_factor": 2.5,
            "closure_prone": True, "road_factor": 1.4, "speed_kmph": 26.0},
    "HIL": {"name": "Chenab & Pir Panjal hills", "temp_mean": 15.0, "temp_season": 10.5,
            "temp_daily": 5.0, "rain_front_prob": 0.014, "monsoon_factor": 2.5,
            "winter_factor": 2.0, "closure_prone": True, "road_factor": 1.65, "speed_kmph": 22.0},
}

#   base_price  : the fair-weather, off-peak fare of a typical trip (₹)
#   base_demand : rides per hour at that fare in average conditions
#   cost        : driver payout + fuel per ride (₹) - the floor the optimiser may never cross
PRODUCTS = {
    "JMU-BIKE":      {"region": "JMU", "vehicle": "bike",      "base_price": 60.0,  "base_demand": 40.0, "cost": 28.0},
    "JMU-ERICKSHAW": {"region": "JMU", "vehicle": "erickshaw", "base_price": 40.0,  "base_demand": 45.0, "cost": 19.0},
    "JMU-AUTO":      {"region": "JMU", "vehicle": "auto",      "base_price": 90.0,  "base_demand": 38.0, "cost": 42.0},
    "JMU-CAB":       {"region": "JMU", "vehicle": "cab",       "base_price": 220.0, "base_demand": 20.0, "cost": 120.0},
    "KSH-AUTO":      {"region": "KSH", "vehicle": "auto",      "base_price": 100.0, "base_demand": 30.0, "cost": 47.0},
    "KSH-CAB":       {"region": "KSH", "vehicle": "cab",       "base_price": 260.0, "base_demand": 18.0, "cost": 140.0},
    "KSH-SHARED":    {"region": "KSH", "vehicle": "shared",    "base_price": 120.0, "base_demand": 28.0, "cost": 62.0},
    "HIL-CAB":       {"region": "HIL", "vehicle": "cab",       "base_price": 320.0, "base_demand": 8.0,  "cost": 175.0},
    "HIL-SHARED":    {"region": "HIL", "vehicle": "shared",    "base_price": 150.0, "base_demand": 14.0, "cost": 78.0},
}

WEATHER_CONDITIONS = ["Clear", "Cloudy", "Rainy", "Stormy", "Snowy"]

START = "2024-01-01"
HOURS = 8760          # one full year per product, so summer yatras and winter snow both appear
# 9 products x 8760 hours = 78,840 rows.
