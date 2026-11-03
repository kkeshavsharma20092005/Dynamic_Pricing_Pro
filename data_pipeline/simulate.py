"""
STEP 5 - Marketplace simulator: do the pricing strategies actually work?

The demand model cannot answer this by itself, because it never sees a driver. Here each
strategy sets an hourly price over the holdout months (Oct-Dec, unseen in training) and
the market responds through the generator's TRUE demand equation plus a supply side:

    price -> riders who want a ride -> drivers available -> wait -> cancellations -> rides

Everything is synthetic. The supply parameters below are assumptions, so these results
compare strategies inside this model of a market. They do not predict real J&K earnings.

Strategies:
    fixed     always the normal fare
    rule      surge on last hour's demand/supply ratio, like a simple ride app
    ml        the demand model's profit optimum (blind to drivers and waits)
    bandit    Thompson sampling: learns prices online from observed profit, no model
    oracle    best price under the true equations, the unreachable upper bound

All strategies obey the same fair-price caps and face the same market, over the same seeds.
"""
import json

import joblib
import numpy as np
import pandas as pd

from config import MODEL_PKL, OUTPUT_DIR, PRODUCTS, RAW_CSV, TRUE_CROSS_ELASTICITY
from features import FEATURES, chronological_split, engineer, load
from generate_data import demand_drivers

SEEDS = 10
MULTIPLIERS = np.round(np.arange(0.70, 1.301, 0.05), 2)
CAP_NORMAL, CAP_HARDSHIP = 1.30, 1.15

# Assumed supply side.
CAPACITY_MARGIN = 1.15          # drivers can serve this share of a typical hour's demand
RIDES_PER_DRIVER_HOUR = 2.0
SUPPLY_PRICE_RESPONSE = 0.6     # 10% higher fares bring 6% more driver hours
BASE_WAIT_MIN = 4.0
WAIT_SLOPE = 14.0
CANCEL_PER_WAIT_MIN = 0.015
MAX_CANCEL = 0.6


def market_frame() -> pd.DataFrame:
    """Holdout rows plus the true expected demand at the normal fare."""
    df = load(RAW_CSV)
    _, test = chronological_split(df)
    test = test.sort_values(["timestamp", "product_id"]).reset_index(drop=True)

    typical = {}
    for product, rows in df.groupby("product_id"):
        typical[product] = float(rows.units_sold.mean())

    frames = []
    for product, rows in test.groupby("product_id", sort=False):
        spec = PRODUCTS[product]
        # demand_drivers ends with a drift on row position, so restore the true clock.
        drift_now = 0.00006 * rows.time_index.to_numpy()
        drift_as_coded = 0.00006 * np.arange(len(rows))
        drivers = demand_drivers(rows) - drift_as_coded + drift_now

        rows = rows.copy()
        rows["base_price"] = spec["base_price"]
        rows["cost"] = spec["cost"]
        rows["lam_base"] = (spec["base_demand"]
                            * (rows.competitor_min_price / spec["base_price"]) ** TRUE_CROSS_ELASTICITY
                            * np.exp(drivers))
        rows["typical_demand"] = typical[product]
        hardship = (rows.road_closed == 1) | rows.weather_condition.isin(["Stormy", "Snowy"])
        rows["cap"] = np.where(hardship, CAP_HARDSHIP, CAP_NORMAL)
        frames.append(rows)
    return pd.concat(frames, ignore_index=True)


COLUMNS = ["base_price", "cost", "lam_base", "true_elasticity", "typical_demand", "road_closed", "is_snowing"]


def as_arrays(m: pd.DataFrame) -> dict:
    """Plain arrays: the online strategies call respond() once per market-hour."""
    return {c: m[c].to_numpy(dtype=float) for c in COLUMNS}


def respond(a: dict, mult: np.ndarray, noise=None):
    """How the market reacts to a price multiplier. Vectorised over rows."""
    price = a["base_price"] * mult
    wanted = a["lam_base"] * mult ** a["true_elasticity"]
    if noise is not None:
        wanted = noise.poisson(wanted).astype(float)

    weather_supply = np.where(a["road_closed"] == 1, 0.5, np.where(a["is_snowing"] == 1, 0.7, 1.0))
    capacity = (a["typical_demand"] * CAPACITY_MARGIN
                * mult ** SUPPLY_PRICE_RESPONSE * weather_supply)
    utilisation = wanted / np.maximum(capacity, 1e-6)
    wait = BASE_WAIT_MIN + WAIT_SLOPE * np.maximum(utilisation - 0.7, 0) ** 1.5
    cancel = np.minimum(CANCEL_PER_WAIT_MIN * wait, MAX_CANCEL)
    completed = np.minimum(wanted * (1 - cancel), capacity)
    profit = (price - a["cost"]) * completed
    return {"completed": completed, "profit": profit, "wait": wait, "wanted": wanted,
            "utilisation": utilisation}


def one_row(a: dict, i: int) -> dict:
    return {c: v[i:i + 1] for c, v in a.items()}


def oracle_multipliers(m: pd.DataFrame) -> np.ndarray:
    a = as_arrays(m)
    profits = np.column_stack([respond(a, np.full(len(m), k))["profit"] for k in MULTIPLIERS])
    allowed = MULTIPLIERS[None, :] <= m.cap.to_numpy()[:, None] + 1e-9
    profits[~allowed] = -np.inf
    return MULTIPLIERS[profits.argmax(axis=1)]


def ml_multipliers(m: pd.DataFrame) -> np.ndarray:
    """The engine's method, batched: predict the demand curve and take the profit peak."""
    model = joblib.load(MODEL_PKL)["model"]
    best = np.ones(len(m))
    best_profit = np.full(len(m), -np.inf)
    for k in MULTIPLIERS:
        candidate = m.copy()
        candidate["our_price"] = m.base_price * k
        demand = np.expm1(model.predict(engineer(candidate)[FEATURES]))
        profit = (candidate.our_price - m.cost) * np.clip(demand, 0, None)
        better = (profit > best_profit).to_numpy() & (k <= m.cap.to_numpy() + 1e-9)
        best = np.where(better, k, best)
        best_profit = np.where(better, profit, best_profit)
    return best


def run_rule(m: pd.DataFrame, rng) -> tuple:
    """Surge from last hour's pressure in the same product; it reacts, one hour late."""
    n = len(m)
    a, caps = as_arrays(m), m.cap.to_numpy()
    mult = np.ones(n)
    results = {key: np.zeros(n) for key in ("completed", "profit", "wait")}
    for index in m.groupby("product_id", sort=False).indices.values():
        pressure = 1.0
        for i in index:
            mult[i] = np.clip(1 + 0.5 * max(pressure - 0.8, 0), 0.70, caps[i])
            out = respond(one_row(a, i), mult[i:i + 1], rng)
            for key in results:
                results[key][i] = out[key][0]
            pressure = out["utilisation"][0]
    return mult, results


def run_bandit(m: pd.DataFrame, rng) -> tuple:
    """Thompson sampling per context on profit, normalised so products can be compared."""
    n = len(m)
    mult = np.ones(n)
    results = {key: np.zeros(n) for key in ("completed", "profit", "wait")}
    rush = (m.rush_intensity > 0.5).astype(int).to_numpy()
    wet = (m.is_raining == 1).astype(int).to_numpy()
    products = m.product_id.to_numpy()
    scale = (m.base_price * m.typical_demand).to_numpy()
    caps = m.cap.to_numpy()
    a = as_arrays(m)

    k = len(MULTIPLIERS)
    stats = {}
    for i in np.argsort(m.timestamp.to_numpy(), kind="stable"):
        key = (products[i], rush[i], wet[i])
        count, total = stats.setdefault(key, (np.zeros(k), np.zeros(k)))
        allowed = MULTIPLIERS <= caps[i] + 1e-9
        mean = (total + 0.5) / (count + 1)
        draws = rng.normal(mean, 0.5 / np.sqrt(count + 1))
        draws[~allowed] = -np.inf
        arm = int(draws.argmax())

        mult[i] = MULTIPLIERS[arm]
        out = respond(one_row(a, i), mult[i:i + 1], rng)
        for name in results:
            results[name][i] = out[name][0]
        count[arm] += 1
        total[arm] += out["profit"][0] / scale[i]
    return mult, results


def summarise(m, mult, outcome) -> dict:
    completed = outcome["completed"]
    return {
        "profit": float(outcome["profit"].sum()),
        "rides": float(completed.sum()),
        "wait_min": float(np.average(outcome["wait"], weights=np.maximum(completed, 1e-6))),
        "avg_multiplier": float(np.average(mult, weights=np.maximum(completed, 1e-6))),
        "pct_hours_at_cap": float((mult >= m.cap.to_numpy() - 1e-9).mean() * 100),
    }


def main():
    m = market_frame()
    print(f"{len(m):,} market-hours, {m.timestamp.min()} .. {m.timestamp.max()}")

    deterministic = {
        "fixed": np.ones(len(m)),
        "ml": ml_multipliers(m),
        "oracle": oracle_multipliers(m),
    }
    runs = {name: [] for name in ["fixed", "rule", "ml", "bandit", "oracle"]}
    segments = {
        "Rush hour": (m.rush_intensity > 0.5).to_numpy(),
        "Snow or storm": m.weather_condition.isin(["Stormy", "Snowy"]).to_numpy(),
        "Road closed": (m.road_closed == 1).to_numpy(),
        "Off-peak": (m.rush_intensity < 0.1).to_numpy(),
    }
    segment_runs = {name: {s: [] for s in segments} for name in runs}

    for seed in range(SEEDS):
        print(f"  seed {seed + 1}/{SEEDS}")
        outcomes = {}
        for name, mult in deterministic.items():
            outcomes[name] = (mult, respond(as_arrays(m), mult, np.random.default_rng(seed)))
        outcomes["rule"] = run_rule(m, np.random.default_rng(seed))
        outcomes["bandit"] = run_bandit(m, np.random.default_rng(seed))

        for name, (mult, outcome) in outcomes.items():
            runs[name].append(summarise(m, mult, outcome))
            for label, mask in segments.items():
                segment_runs[name][label].append(float(outcome["profit"][mask].sum()))

    oracle_profit = np.array([r["profit"] for r in runs["oracle"]])
    fixed_profit = np.array([r["profit"] for r in runs["fixed"]])
    report = {}
    for name, rows in runs.items():
        table = pd.DataFrame(rows)
        profit = table.profit.to_numpy()
        report[name] = {
            **{c: float(table[c].mean()) for c in table.columns},
            "profit_std": float(table.profit.std(ddof=1)),
            "profit_vs_fixed_pct": float(((profit / fixed_profit - 1) * 100).mean()),
            "profit_vs_fixed_pct_std": float(((profit / fixed_profit - 1) * 100).std(ddof=1)),
            "regret_vs_oracle_pct": float(((1 - profit / oracle_profit) * 100).mean()),
            "profit_by_segment": {s: float(np.mean(v)) for s, v in segment_runs[name].items()},
        }

    (OUTPUT_DIR / "simulation.json").write_text(json.dumps({
        "seeds": SEEDS,
        "market_hours": len(m),
        "period": [str(m.timestamp.min()), str(m.timestamp.max())],
        "caps": {"normal": CAP_NORMAL, "hardship": CAP_HARDSHIP},
        "assumptions": ("Synthetic market. Supply response, waits and cancellations are "
                        "assumed values, so results compare strategies within this model only."),
        "strategies": report,
    }, indent=2))

    print(f"\n{'strategy':<10}{'profit vs fixed':>18}{'regret':>9}{'rides':>11}{'wait':>7}{'at cap':>8}")
    for name, r in report.items():
        print(f"{name:<10}{r['profit_vs_fixed_pct']:>+11.1f}% ±{r['profit_vs_fixed_pct_std']:<4.1f}"
              f"{r['regret_vs_oracle_pct']:>8.1f}%{r['rides']:>11,.0f}{r['wait_min']:>7.1f}"
              f"{r['pct_hours_at_cap']:>7.0f}%")


if __name__ == "__main__":
    main()
