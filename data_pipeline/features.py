"""
STEP 2 - Feature engineering.

Imported by the TRAINING pipeline and by the LIVE API. That shared import is a
correctness requirement, not code tidiness.

WHY, CONCRETELY:
The pricing engine works by asking the model "how many rides at ₹180? at ₹190? at ₹200?"
Every one of those questions changes `our_price` - and therefore also changes
`competitor_price_ratio`, `price_gap_vs_min`, `log_price`, `is_cheapest`, and
`margin_pct`. If the engine only swapped `our_price` and left the ratios at their
old values, it would score a row that CANNOT EXIST: a ride priced at ₹200 whose
price-to-competitor ratio still says ₹180. The model would return confident nonsense
and the optimiser would climb a fake curve.

So: one function, called by both. Swap the price, re-derive everything downstream.

--------------------------------------------------------------------------------
HOW THE CROSS-FEATURES DRIVE PRICING DECISIONS
--------------------------------------------------------------------------------
competitor_price_ratio = our_price / competitor_min_price
    The single most decision-relevant feature in the model. Shoppers do not judge
    ₹180 in the abstract; they judge it against the cheapest alternative on screen.
    Raw price alone cannot express "we are 8% over the cheapest rival" - and that
    ratio, not the rupee amount, is what collapses demand. When the engine sweeps
    candidate prices, this ratio is what actually moves, and its slope IS the demand
    curve the optimiser climbs.

weather_demand_index
    Compresses temperature + precipitation into one "how much does the world want
    this today" signal. Rain drives people into paid transport; extreme heat or cold
    suppresses discretionary buying. Crucially it is a DEMAND SHIFTER, not a price
    term: it moves the curve up or down without changing its slope. Practical effect
    on the engine: on a rainy rush-hour evening the whole demand curve lifts, so the
    profit-maximising price rises - the model surges for you, and can say why.

hour_sin / hour_cos (cyclical encoding)
    Hour 23 and hour 0 are one hour apart, but as raw integers they are 23 apart.
    Feed the integer and a linear model believes midnight is maximally distant from
    11pm, so it cannot learn the twin commuter peaks that drive demand. The sine and
    cosine pair puts the clock back on a circle. Without this, the model mis-times
    every surge window.

rush_x_price_ratio / rain_x_price_ratio (interactions)
    Price SENSITIVITY is not constant. A commuter in the rain at 6pm barely looks at
    price; a browser on a dry Sunday afternoon shops around. These interactions let
    elasticity itself vary with context, which is what turns one global price into a
    genuinely dynamic one.
"""
import numpy as np
import pandas as pd

TARGET = "units_sold"

# Never features.
#   revenue / total_sales : revenue = price x units is the target multiplied by a known
#                           number. A model handed it "predicts" demand by dividing -
#                           superb R2, zero learning. (We never generate it, but guard.)
#   true_elasticity       : the generator's answer key. Using it would be marking your
#                           own exam. It sits in the CSV for auditing only.
FORBIDDEN = ["revenue", "total_sales", "units_sold", "true_elasticity"]

NUMERIC = [
    # the decision variable
    "our_price", "log_price",
    # --- COMPETITOR CROSS-FEATURES ---
    "competitor_price_ratio",      # our_price / competitor_min_price
    "competitor_mean_ratio",       # our_price / competitor_mean_price
    "price_gap_vs_min",            # absolute ₹ gap
    "is_cheapest",                 # binary: are we the cheapest on screen?
    "competitor_spread",           # how tightly clustered is the market?
    "competitor_min_price", "competitor_mean_price",
    # --- WEATHER ---
    "temperature", "precipitation",
    "temp_comfort",                # quadratic comfort curve, peaks at 21C
    "weather_demand_index",        # composite demand shifter
    "is_raining",
    # --- CYCLICAL TIME ---
    "hour_sin", "hour_cos", "dow_sin", "dow_cos", "month_sin", "month_cos",
    "rush_intensity", "is_weekend", "is_holiday", "time_index",
    # --- INTERACTIONS (context-dependent price sensitivity) ---
    "rush_x_price_ratio", "rain_x_price_ratio", "weekend_x_price_ratio",
    # These three are what let ELASTICITY ITSELF vary with context. In a log-demand
    # model the coefficient on log_price IS the elasticity, so a coefficient on
    # (rush x log_price) is literally "how much rush hour shifts the elasticity".
    # Without them a linear model can only ever fit ONE global slope, and the whole
    # premise of dynamic pricing - that sensitivity changes hour to hour - is lost.
    "rush_x_logprice", "rain_x_logprice", "weekend_x_logprice",
    # --- MARGIN ---
    "margin_pct", "unit_cost",
    # --- DEMAND HISTORY (known at pricing time; shifted, so never leakage) ---
    "demand_lag_1h", "demand_lag_24h", "demand_roll_24h",
]

CATEGORICAL = ["product_id", "weather_condition"]
FEATURES = NUMERIC + CATEGORICAL

IDEAL_TEMP_C = 21.0


def engineer(df: pd.DataFrame) -> pd.DataFrame:
    """
    Derive every model feature. Row-safe: works on one candidate price or on 8,760.

    Assumes the caller supplied the raw context: our_price, unit_cost, competitor
    prices, temperature, precipitation, weather_condition, hour, day_of_week, month,
    is_weekend, is_holiday, time_index, and the demand lags.
    """
    d = df.copy()

    price = d["our_price"].clip(lower=0.01)
    d["log_price"] = np.log(price)

    # ---------- COMPETITOR CROSS-FEATURES ----------
    comp_cols = ["competitor_1_price", "competitor_2_price", "competitor_3_price"]
    if all(c in d.columns for c in comp_cols):
        C = d[comp_cols].clip(lower=0.01)
        d["competitor_min_price"] = C.min(axis=1)
        d["competitor_mean_price"] = C.mean(axis=1)
        d["competitor_spread"] = C.max(axis=1) - C.min(axis=1)
    else:
        d["competitor_spread"] = (
            d["competitor_mean_price"] - d["competitor_min_price"]).clip(lower=0)

    cmin = d["competitor_min_price"].clip(lower=0.01)
    cmean = d["competitor_mean_price"].clip(lower=0.01)

    d["competitor_price_ratio"] = price / cmin      # THE decisive feature
    d["competitor_mean_ratio"] = price / cmean
    d["price_gap_vs_min"] = price - cmin
    d["is_cheapest"] = (price <= cmin).astype(int)

    # ---------- WEATHER ----------
    # Quadratic, not linear. Demand peaks at a comfortable temperature and falls off
    # in BOTH directions; a linear term cannot express that and leaves elasticity
    # biased (generate_data.py demonstrates this costing 0.38 of elasticity).
    d["temp_comfort"] = -((d["temperature"] - IDEAL_TEMP_C) ** 2) / 100.0
    d["is_raining"] = (d["precipitation"] > 0.1).astype(int)

    # Composite demand shifter: rain lifts demand, temperature discomfort suppresses it.
    d["weather_demand_index"] = (
        1.0
        + 0.030 * d["precipitation"].clip(upper=15)
        + 3.0 * d["temp_comfort"]
    )

    # ---------- CYCLICAL TIME ----------
    # 23:00 and 00:00 are adjacent on a clock but 23 apart as integers.
    d["hour_sin"] = np.sin(2 * np.pi * d["hour"] / 24)
    d["hour_cos"] = np.cos(2 * np.pi * d["hour"] / 24)
    d["dow_sin"] = np.sin(2 * np.pi * d["day_of_week"] / 7)
    d["dow_cos"] = np.cos(2 * np.pi * d["day_of_week"] / 7)
    d["month_sin"] = np.sin(2 * np.pi * d["month"] / 12)
    d["month_cos"] = np.cos(2 * np.pi * d["month"] / 12)

    # Twin commuter peaks (08:00, 18:00).
    d["rush_intensity"] = (
        np.exp(-0.5 * ((d["hour"] - 8) / 1.8) ** 2)
        + 1.15 * np.exp(-0.5 * ((d["hour"] - 18) / 2.0) ** 2)
    )

    # ---------- INTERACTIONS: let elasticity vary with context ----------
    d["rush_x_price_ratio"] = d["rush_intensity"] * d["competitor_price_ratio"]
    d["rain_x_price_ratio"] = d["is_raining"] * d["competitor_price_ratio"]
    d["weekend_x_price_ratio"] = d["is_weekend"] * d["competitor_price_ratio"]

    # The elasticity-shifters. Fitted elasticity in context c becomes
    #     e(c) = b[log_price] + b[rush_x_logprice]*rush + b[rain_x_logprice]*rain
    # so the model can learn "commuters in the rain barely look at price" - which is
    # exactly the surge opportunity a static price leaves on the table.
    d["rush_x_logprice"] = d["rush_intensity"] * d["log_price"]
    d["rain_x_logprice"] = d["is_raining"] * d["log_price"]
    d["weekend_x_logprice"] = d["is_weekend"] * d["log_price"]

    # ---------- MARGIN ----------
    d["margin_pct"] = (price - d["unit_cost"]) / price

    return d


def load(path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["timestamp"])
    df = engineer(df)
    return df.sort_values("timestamp").reset_index(drop=True)


def chronological_split(df: pd.DataFrame, test_frac=0.2):
    """
    Train on the past, test on the future. A random split would let the model peek at
    tomorrow while predicting today - on time-series data that inflates every metric.
    """
    cut = df["timestamp"].quantile(1 - test_frac)
    return (df[df.timestamp < cut].reset_index(drop=True),
            df[df.timestamp >= cut].reset_index(drop=True))


def expanding_window_cv(df: pd.DataFrame, n_splits=4, min_train_frac=0.4):
    """
    Time-aware CV folds for GridSearchCV, cut on TIME rather than row position.

    This is panel data: 3 SKUs share every timestamp. sklearn's TimeSeriesSplit cuts
    on row index, which would tear a single hour across a fold boundary and train on
    one SKU's 3pm while testing another SKU's 3pm. Splitting on the timestamp keeps
    every fold an honest past -> future test.
    """
    times = np.sort(df.timestamp.unique())
    start = int(len(times) * min_train_frac)
    step = (len(times) - start) // n_splits
    t = df.timestamp.values

    for i in range(n_splits):
        cut = start + i * step
        end = cut + step
        if end > len(times):
            break
        tr = np.where(t < times[cut])[0]
        te = np.where((t >= times[cut]) & (t < times[min(end, len(times) - 1)]))[0]
        if len(tr) and len(te):
            yield tr, te
