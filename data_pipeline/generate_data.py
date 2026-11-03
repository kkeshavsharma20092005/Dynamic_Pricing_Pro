"""
STEP 1 - Synthetic data generation for a Jammu & Kashmir ride market.

Anyone can emit random numbers. What makes a synthetic dataset worth modelling is
that it contains a REAL structure to be recovered, plus the REAL traps that make
recovery hard. This generator builds in three of them on purpose.

TRAP 1 - ENDOGENEITY (the one that ruins most pricing projects).
    Real businesses surge-price: they RAISE prices exactly when demand is high.
    So price is correlated with the unobserved demand drivers. Regress demand on
    price without controlling for those drivers and you get an elasticity that is
    attenuated toward zero, or even POSITIVE ("raise price, sell more"), which
    would make the optimiser recommend an infinite price.
    We generate prices that partly respond to rush hour / weekend / weather, so
    the trap is live. The fix is not a trick - it is including those same drivers
    as features. evaluate.py proves the fix works.

TRAP 2 - IDENTIFICATION.
    If price were a pure deterministic function of the demand drivers, elasticity
    would be mathematically unrecoverable - price would carry no independent
    information. Real firms run promos and pricing tests; we inject that same
    exogenous price variation. Without it, no model on earth could find the curve.

TRAP 3 - COUNT NOISE.
    Demand is a count, not a smooth real number. We draw from a Poisson so the
    variance scales with the mean, exactly like real sales.

GROUND TRUTH: demand is built as a log-linear function of price, so every row's true
own-price elasticity is known EXACTLY (see config.TRUE_BASE_ELASTICITY and its shifts).
It is written to the CSV as `true_elasticity` for auditing, and it is listed in
features.FORBIDDEN so it can never be used as a model input. It is the answer key.

This is assumed behaviour, not observed J&K ride data: the climate, calendar and fares
encode the assumptions listed in config.py and season.py.
"""
import json

import numpy as np
import pandas as pd

from config import (GROUND_TRUTH_JSON, HOURS, PRODUCTS, RAW_CSV, REGIONS, SEED, START,
                    TRUE_BASE_ELASTICITY, TRUE_CROSS_ELASTICITY,
                    TRUE_PILGRIM_ELASTICITY_SHIFT, TRUE_RAIN_ELASTICITY_SHIFT,
                    TRUE_RUSH_ELASTICITY_SHIFT, TRUE_SNOW_ELASTICITY_SHIFT)
from season import is_holiday, pilgrim_index, tourist_index

rng = np.random.default_rng(SEED)


# --------------------------------------------------------------------------
# Exogenous world: time and weather happen to us; we do not choose them.
# --------------------------------------------------------------------------
def build_world(region: str) -> pd.DataFrame:
    spec = REGIONS[region]
    ts = pd.date_range(START, periods=HOURS, freq="h")
    w = pd.DataFrame({"timestamp": ts})
    w["hour"] = w.timestamp.dt.hour
    w["day_of_week"] = w.timestamp.dt.dayofweek          # 0=Mon
    w["month"] = w.timestamp.dt.month
    w["day_of_year"] = w.timestamp.dt.dayofyear
    w["is_weekend"] = (w.day_of_week >= 5).astype(int)

    # Two commuter peaks (08:00 and 18:00) - the classic urban demand shape.
    w["rush_intensity"] = (
        np.exp(-0.5 * ((w.hour - 8) / 1.8) ** 2)
        + 1.15 * np.exp(-0.5 * ((w.hour - 18) / 2.0) ** 2)
    )

    # Hottest in mid-July, coldest in mid-January, plus a day/night cycle and noise.
    season = spec["temp_season"] * np.sin(2 * np.pi * (w.day_of_year - 105) / 365.25)
    daily = spec["temp_daily"] * np.sin(2 * np.pi * (w.hour - 9) / 24)
    w["temperature"] = spec["temp_mean"] + season + daily + rng.normal(0, 2.2, len(w))

    # Rain arrives in multi-hour fronts: more in the monsoon, and in winter when
    # western disturbances bring snow to the valley and the high roads.
    monsoon = w.day_of_year.between(182, 258)
    winter = w.month.isin([12, 1, 2, 3])
    front_prob = spec["rain_front_prob"] * np.where(
        monsoon, spec["monsoon_factor"], np.where(winter, spec["winter_factor"], 1.0))
    front = rng.random(len(w)) < front_prob
    front = pd.Series(front).rolling(6, min_periods=1).max().astype(bool).values
    w["precipitation"] = np.where(front, rng.gamma(2.0, 1.8, len(w)), 0.0).round(2)

    w["weather_condition"] = pd.cut(
        w.precipitation, bins=[-0.01, 0.01, 2.0, 6.0, np.inf],
        labels=["Clear", "Cloudy", "Rainy", "Stormy"],
    ).astype(str)
    is_snowing = (w.precipitation > 0.1) & (w.temperature <= 1.0)
    w.loc[is_snowing, "weather_condition"] = "Snowy"

    # A heavy storm closes exposed roads, and they take half a day to reopen.
    hazard = (w.precipitation >= 6.0) if spec["closure_prone"] else pd.Series(False, index=w.index)
    w["road_closed"] = hazard.astype(int).rolling(12, min_periods=1).max().astype(int)

    w["is_holiday"] = is_holiday(w.day_of_year)
    w["pilgrim_index"] = pilgrim_index(region, w.day_of_year)
    w["tourist_index"] = tourist_index(region, w.month)
    return w


def demand_drivers(w: pd.DataFrame) -> np.ndarray:
    """
    Everything that moves demand EXCEPT price. This is the confounder: the pricing
    rule below reads it, and so does the demand equation. That double dependence is
    precisely what makes naive elasticity estimates wrong.
    """
    return (
        0.85 * w.rush_intensity
        + 0.22 * w.is_weekend
        + 0.40 * w.is_holiday
        + 0.55 * w.pilgrim_index
        + 0.35 * w.tourist_index
        - 0.50 * w.road_closed
        # Rain pushes people into paid transport - a genuine demand lift.
        + 0.030 * w.precipitation
        # Comfort curve: demand peaks near 21C and falls off in either direction.
        - 0.0015 * (w.temperature - 21.0) ** 2
        # Mild upward drift over the period.
        + 0.00006 * np.arange(len(w))
    ).to_numpy()


def generate() -> pd.DataFrame:
    worlds = {region: build_world(region) for region in REGIONS}
    frames = []

    for sku, spec in PRODUCTS.items():
        d = worlds[spec["region"]].copy()
        drivers = demand_drivers(d)
        d["product_id"] = sku
        d["unit_cost"] = spec["cost"]
        base_p, base_q = spec["base_price"], spec["base_demand"]

        # ---- COMPETITORS: three local rivals drifting around the base price ----
        drift = np.cumsum(rng.normal(0, 0.0015, len(d)))         # slow market drift
        comps = []
        for i in range(1, 4):
            offset = rng.normal(1.0 + 0.03 * (i - 2), 0.05)
            noise = rng.normal(0, 0.035, len(d))
            comps.append(base_p * offset * np.exp(drift + noise))
        C = np.vstack(comps)
        d["competitor_1_price"] = C[0].round(2)
        d["competitor_2_price"] = C[1].round(2)
        d["competitor_3_price"] = C[2].round(2)
        d["competitor_mean_price"] = C.mean(axis=0).round(2)
        d["competitor_min_price"] = C.min(axis=0).round(2)

        # ---- OUR PRICE: a realistic surge rule + exogenous experimentation ----
        # TRAP 1 lives here: price responds to the SAME drivers that move demand.
        surge = 0.16 * (drivers - drivers.mean()) / drivers.std()
        follow = 0.10 * (d.competitor_mean_price / base_p - 1.0)   # we track rivals
        # TRAP 2's antidote: promos and price tests give price independent variation.
        experiment = rng.normal(0, 0.085, len(d))
        promo = np.where(rng.random(len(d)) < 0.07, rng.uniform(-0.28, -0.08, len(d)), 0.0)

        price = base_p * (1 + surge + follow + experiment + promo)
        d["base_price"] = base_p
        d["our_price"] = np.clip(price, spec["cost"] * 1.05, base_p * 1.9).round(2)

        # ---- TRUE DEMAND EQUATION ----
        # Elasticity is context-dependent: rush hour, rain, snow and yatra crowds make
        # customers LESS price-sensitive (elasticity closer to zero). We record the
        # exact per-row elasticity so evaluate.py can check the model recovers the
        # whole PATTERN, not merely an average.
        is_wet = (d.precipitation > 0.1).astype(float)
        is_snowing = ((d.precipitation > 0.1) & (d.temperature <= 1.0)).astype(float)
        d["true_elasticity"] = (
            TRUE_BASE_ELASTICITY
            + TRUE_RUSH_ELASTICITY_SHIFT * d.rush_intensity
            + TRUE_RAIN_ELASTICITY_SHIFT * is_wet
            + TRUE_SNOW_ELASTICITY_SHIFT * is_snowing
            + TRUE_PILGRIM_ELASTICITY_SHIFT * d.pilgrim_index
        )

        log_q = (
            np.log(base_q)
            + d.true_elasticity * np.log(d.our_price / base_p)
            + TRUE_CROSS_ELASTICITY * np.log(d.competitor_min_price / base_p)
            + drivers
        )
        lam = np.clip(np.exp(log_q), 0.05, None)
        d["units_sold"] = rng.poisson(lam)          # TRAP 3: count noise

        # Lagged demand: known when you set the next hour's price, so it is a legal
        # feature, not leakage. Shifted by 1 - it can never see its own row.
        d["demand_lag_1h"] = d.units_sold.shift(1).bfill()
        d["demand_lag_24h"] = d.units_sold.shift(24).bfill()
        d["demand_roll_24h"] = d.units_sold.shift(1).rolling(24, min_periods=1).mean().bfill()

        # A clock the model can see. The demand equation contains a slow upward
        # drift; without a time index the model cannot separate that drift from
        # price, and elasticity picks up the difference as bias.
        d["time_index"] = np.arange(len(d))

        frames.append(d)

    df = pd.concat(frames, ignore_index=True).sort_values(
        ["timestamp", "product_id"]).reset_index(drop=True)

    # NOTE: we deliberately do NOT emit a `revenue` column. revenue = price x units
    # would be a perfect target leak - a model handed it would just divide.
    return df


def main():
    df = generate()
    df.to_csv(RAW_CSV, index=False, float_format="%.4f")

    # The exact average true elasticity across the generated data. `true_elasticity`
    # is written to the CSV for auditing but is NEVER a model feature (see
    # features.FORBIDDEN) - it is the answer key, not an input.
    mean_true = float(df.true_elasticity.mean())

    GROUND_TRUTH_JSON.write_text(json.dumps({
        "mean_true_own_price_elasticity": round(mean_true, 4),
        "base_elasticity": TRUE_BASE_ELASTICITY,
        "rush_shift": TRUE_RUSH_ELASTICITY_SHIFT,
        "rain_shift": TRUE_RAIN_ELASTICITY_SHIFT,
        "snow_shift": TRUE_SNOW_ELASTICITY_SHIFT,
        "pilgrim_shift": TRUE_PILGRIM_ELASTICITY_SHIFT,
        "true_cross_price_elasticity": TRUE_CROSS_ELASTICITY,
        "formula": ("e_i = base + rush_shift*rush_intensity + rain_shift*is_wet "
                    "+ snow_shift*is_snowing + pilgrim_shift*pilgrim_index"),
        "note": "The model never sees these. evaluate.py checks recovery.",
    }, indent=2))

    print(f"Generated {len(df):,} rows x {df.shape[1]} cols -> {RAW_CSV}")
    print(f"  TRUE elasticity: mean {mean_true:+.3f}, "
          f"range {df.true_elasticity.min():+.2f} .. {df.true_elasticity.max():+.2f}")
    print(f"  products : {df.product_id.nunique()}")
    print(f"  span     : {df.timestamp.min()} .. {df.timestamp.max()}")
    print(f"  weather  : { {k: int(v) for k, v in df.weather_condition.value_counts().items()} }")
    print(f"  road closed: {df.road_closed.mean() * 100:.1f}% of rows")
    print(f"  units    : mean {df.units_sold.mean():.1f}, "
          f"min {df.units_sold.min()}, max {df.units_sold.max()}")
    print(f"  missing  : {df.isna().sum().sum()}")

    # ---- Prove the traps are actually live in the data we just wrote ----
    print("\n" + "=" * 72)
    print("IS THE ENDOGENEITY TRAP ARMED?  (naive vs. controlled elasticity)")
    print("=" * 72)
    d = df[df.units_sold > 0].copy()
    lp, lq = np.log(d.our_price), np.log(d.units_sold)
    TRUE = mean_true

    # Within a product, so the price gap between a bike and a cab is not read as demand.
    within = lambda s: s - s.groupby(d.product_id).transform("mean")
    naive = np.polyfit(within(lp), within(lq), 1)[0]

    # Control for the confounders by partialling them out of BOTH price and demand.
    from sklearn.linear_model import LinearRegression

    def partial_out(Z):
        rp = lp - LinearRegression().fit(Z, lp).predict(Z)
        rq = lq - LinearRegression().fit(Z, lq).predict(Z)
        return np.polyfit(rp, rq, 1)[0]

    dummies = pd.get_dummies(
        d[["hour", "day_of_week", "product_id"]].astype(str)).to_numpy(float)
    calendar = np.column_stack([
        d.precipitation, d.is_holiday, d.pilgrim_index, d.tourist_index, d.road_closed,
        np.log(d.competitor_min_price),
    ])

    # Partial controls: temperature enters LINEARLY, and the time drift is missing.
    partial = partial_out(np.column_stack([dummies, calendar, d.temperature]))

    # Full controls: temperature is QUADRATIC in the true demand equation, and the
    # drift is real. Get the functional form wrong and the omitted piece leaks
    # straight into the price coefficient.
    full = partial_out(np.column_stack([
        dummies, calendar, d.temperature, (d.temperature - 21.0) ** 2, d.time_index,
    ]))

    print(f"  TRUE elasticity (ground truth)      : {TRUE:+.2f}")
    print(f"  Naive log-log regression            : {naive:+.2f}   "
          f"(off by {abs(naive - TRUE):.2f})  <- surge-price bias")
    print(f"  Controls, wrong functional form     : {partial:+.2f}   "
          f"(off by {abs(partial - TRUE):.2f})  <- linear temp, no trend")
    print(f"  Controls, correct functional form   : {full:+.2f}   "
          f"(off by {abs(full - TRUE):.2f})  <- recovers the truth")
    print("\n  Two lessons the naive number hides:")
    print(f"   1. Omitting a confounder biases elasticity ({naive:+.2f} vs {TRUE:+.2f}).")
    print("   2. Including it with the WRONG SHAPE still biases it. Temperature")
    print("      affects demand quadratically; modelling it linearly leaves bias behind.")
    print("  This is why features.py encodes temp_comfort and cyclical time explicitly.")


if __name__ == "__main__":
    main()
