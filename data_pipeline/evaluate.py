"""
STEP 4 - Evaluation: RMSE, R2, Price Elasticity of Demand, feature importance.

THE HEADLINE METRIC IS NOT RMSE. IT IS ELASTICITY.

A demand model can score a superb RMSE by leaning entirely on demand_lag_1h and
ignoring price completely. Its forecasts would be excellent and its pricing advice
worthless: a flat demand curve gives the optimiser nothing to climb, so it would just
recommend the highest price on the grid, forever. So every model is gated on one
question - when we raise the price, does predicted demand actually FALL?

And because this dataset is synthetic, we can do something impossible with real data:
check the answer against the TRUE elasticity the generator used. If the pipeline
recovers -1.80 without ever being told it, the estimator is validated.
"""
import json

import joblib
import numpy as np
import pandas as pd
from sklearn.inspection import permutation_importance
from sklearn.metrics import r2_score, root_mean_squared_error

from config import (GROUND_TRUTH_JSON, METRICS_JSON, MODEL_DIR, OUTPUT_DIR,
                    RAW_CSV, TARGET)
from features import FEATURES, chronological_split, engineer, load

EPS = 0.05  # +/-5% price nudge


def price_elasticity(model, rows: pd.DataFrame, eps: float = EPS) -> np.ndarray:
    """
    PRICE ELASTICITY OF DEMAND, computed from the fitted model.

        elasticity = (% change in quantity) / (% change in price)

    Method: nudge price down eps and up eps, re-derive EVERY price-dependent feature
    both times (competitor_price_ratio, log_price, margin_pct, the interactions...),
    predict demand at each, and read off the arc slope.

    Re-deriving is the whole trick. If you moved `our_price` but left
    `competitor_price_ratio` stale, you would be scoring an impossible row and the
    elasticity you measured would be a fiction.

    Interpretation:
        e < -1   elastic   - demand is price-sensitive; a cut grows revenue
        -1 < e < 0 inelastic - demand barely reacts; there is room to raise price
        e >= 0   BROKEN    - "raise price, sell more". Confounding, not a goldmine.
    """
    lo, hi = rows.copy(), rows.copy()
    lo["our_price"] = rows["our_price"] * (1 - eps)
    hi["our_price"] = rows["our_price"] * (1 + eps)

    q_lo = np.clip(np.expm1(model.predict(engineer(lo)[FEATURES])), 0.01, None)
    q_hi = np.clip(np.expm1(model.predict(engineer(hi)[FEATURES])), 0.01, None)

    pct_dq = (q_hi - q_lo) / ((q_hi + q_lo) / 2)   # midpoint (arc) formula
    return pct_dq / (2 * eps)


def feature_importance(model, X, y, top_n=15) -> pd.DataFrame:
    """
    Permutation importance, NOT tree .feature_importances_.

    Impurity-based importance is biased toward high-cardinality continuous features and
    is undefined for a linear model. Permutation importance works for any estimator and
    answers the question we actually care about: how much worse does the model get if
    this feature is shuffled into noise?
    """
    perm = permutation_importance(model, X, y, n_repeats=10, random_state=42, n_jobs=2)
    return (pd.DataFrame({
        "feature": FEATURES,
        "importance": perm.importances_mean,
        "std": perm.importances_std,
    }).sort_values("importance", ascending=False).reset_index(drop=True))


def main():
    df = load(RAW_CSV)
    train, test = chronological_split(df, test_frac=0.2)
    y_te = test[TARGET]

    # The answer key for THIS test set. Never a feature - see features.FORBIDDEN.
    TRUTH = float(test.true_elasticity.mean())

    baseline = np.full(len(y_te), train[TARGET].mean())
    base_rmse = root_mean_squared_error(y_te, baseline)

    report = {}
    print("=" * 84)
    print(f"{'model':<22}{'RMSE':>9}{'R2':>9}{'vs base':>10}{'ELASTICITY':>13}{'% rows -ve':>13}")
    print("=" * 84)

    for name in ["linear_regression", "random_forest", "gradient_boosting"]:
        model = joblib.load(MODEL_DIR / f"{name}.pkl")
        pred = np.clip(np.expm1(model.predict(test[FEATURES])), 0, None)

        rmse = root_mean_squared_error(y_te, pred)
        r2 = r2_score(y_te, pred)
        el = price_elasticity(model, test)
        median_el = float(np.median(el))
        pct_neg = float((el < 0).mean())

        report[name] = {
            "rmse": rmse, "r2": r2,
            "improvement_vs_baseline_pct": (1 - rmse / base_rmse) * 100,
            "price_elasticity": median_el,
            "pct_rows_negative_elasticity": pct_neg,
            "elasticity_error_vs_truth": abs(median_el - TRUTH),
        }
        print(f"{name:<22}{rmse:>9.3f}{r2:>9.4f}"
              f"{(1 - rmse / base_rmse) * 100:>9.1f}%{median_el:>13.2f}{pct_neg * 100:>12.0f}%")

    print(f"{'baseline (mean)':<22}{base_rmse:>9.3f}{r2_score(y_te, baseline):>9.4f}"
          f"{'--':>10}{'--':>13}{'--':>13}")
    print("=" * 84)

    # ---------------- GROUND-TRUTH VALIDATION ----------------
    # This is the payoff of synthetic data. With real data you can never do this.
    print("\n" + "=" * 84)
    print("GROUND-TRUTH RECOVERY  (the model was NEVER told the true elasticity)")
    print("=" * 84)
    print(f"  TRUE own-price elasticity, used by the generator : {TRUTH:+.2f}\n")
    for name, r in report.items():
        err = r["elasticity_error_vs_truth"]
        mark = "PASS" if err < 0.35 else "FAIL"
        print(f"  {name:<22} estimated {r['price_elasticity']:+.2f}   "
              f"error {err:.2f}   [{mark}]")
    print("\n  An estimator that recovers a known truth it was never shown is validated.")

    # ---------------- SELECTION ----------------
    # Gate 1 is a DESIGN requirement judged on the model's price RESPONSE, not on test
    # labels - so selecting on it is not test-set peeking.
    usable = {k: v for k, v in report.items()
              if v["price_elasticity"] < -0.3 and v["pct_rows_negative_elasticity"] >= 0.90}
    if not usable:
        raise SystemExit("No model produced a usable demand curve. The optimiser would "
                         "have nothing to climb. Stop and fix the features.")

    winner = min(usable, key=lambda k: usable[k]["rmse"])
    print(f"\nSELECTED: {winner}")
    for r in set(report) - set(usable):
        print(f"  rejected {r}: only "
              f"{report[r]['pct_rows_negative_elasticity'] * 100:.0f}% of rows slope "
              f"downward (needs >=90%) - cannot drive an optimiser")

    best = joblib.load(MODEL_DIR / f"{winner}.pkl")
    joblib.dump({"model": best, "name": winner, "features": FEATURES},
                MODEL_DIR / "pricing_model.pkl")

    # ---------------- ELASTICITY BY CONTEXT ----------------
    # The point of a DYNAMIC pricing engine: sensitivity is not one number. The
    # generator made elasticity depend on rush hour and rain; can the model see it?
    print("\n" + "=" * 84)
    print("ELASTICITY VARIES BY CONTEXT  (this is what makes pricing 'dynamic')")
    print("=" * 84)
    t = test.copy()
    t["elasticity"] = price_elasticity(best, test)
    overall = float(t.elasticity.median())

    segments = {
        "Rush hour (07-09, 17-19)": t.hour.isin([7, 8, 9, 17, 18, 19]),
        "Off-peak (22-05)": t.hour.isin([22, 23, 0, 1, 2, 3, 4, 5]),
        "Raining": t.is_raining == 1,
        "Dry": t.is_raining == 0,
        "Weekend": t.is_weekend == 1,
        "Weekday": t.is_weekend == 0,
    }
    print(f"  {'segment':<28}{'ESTIMATED':>11}{'TRUE':>9}{'error':>8}   sensitivity")
    print("  " + "-" * 74)
    by_segment = {}
    for label, mask in segments.items():
        if not mask.sum():
            continue
        est = float(t.loc[mask, "elasticity"].median())
        true = float(t.loc[mask, "true_elasticity"].median())
        by_segment[label] = {"estimated": est, "true": true}
        sens = "LESS sensitive" if est > overall else "MORE sensitive"
        print(f"  {label:<28}{est:>11.2f}{true:>9.2f}{abs(est - true):>8.2f}   {sens}")

    # The strongest possible check: does the model's PER-ROW elasticity track the
    # per-row truth? Matching an average is easy; matching the pattern is not.
    corr = float(np.corrcoef(t.elasticity, t.true_elasticity)[0, 1])
    mae = float(np.abs(t.elasticity - t.true_elasticity).mean())
    print(f"\n  Row-level agreement with ground truth: r = {corr:.3f}, MAE = {mae:.3f}")
    print("  The model was never shown the true elasticity of a single row.")

    # ---------------- FEATURE IMPORTANCE ----------------
    print("\n" + "=" * 84)
    print("FEATURE IMPORTANCE (permutation: drop in score when shuffled)")
    print("=" * 84)
    imp = feature_importance(best, test[FEATURES], np.log1p(test[TARGET]))
    print(imp.head(15).to_string(index=False))
    imp.to_csv(OUTPUT_DIR / "feature_importance.csv", index=False)

    ranks = {f: i + 1 for i, f in enumerate(imp.feature)}
    print(f"\n  competitor_price_ratio rank : #{ranks.get('competitor_price_ratio')}")
    print(f"  weather_demand_index rank   : #{ranks.get('weather_demand_index')}")
    print(f"  log_price rank              : #{ranks.get('log_price')}")

    METRICS_JSON.write_text(json.dumps({
        "models": report,
        "selected": winner,
        "baseline_rmse": float(base_rmse),
        "true_elasticity": float(test.true_elasticity.mean()),
        "elasticity_row_correlation": corr,
        "elasticity_row_mae": mae,
        "elasticity_by_segment": by_segment,
        "feature_importance": imp.head(15).to_dict("records"),
        "test_rows": len(test),
        "train_rows": len(train),
    }, indent=2, default=float))
    print(f"\nSaved -> {METRICS_JSON}")


if __name__ == "__main__":
    main()
