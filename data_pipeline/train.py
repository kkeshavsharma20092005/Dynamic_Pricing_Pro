"""
STEP 3 - Multi-model pipeline + GridSearchCV.

Three families compete: LinearRegression (as Ridge, its regularised form),
RandomForest, and GradientBoosting. Every one is wrapped in a Pipeline so that
scaling and one-hot encoding are fitted INSIDE each CV fold - fit the scaler on the
full dataset first and you have leaked test-set statistics into training, and every
score you report afterwards is inflated.

TARGET = log1p(units_sold), not units_sold.
Demand is multiplicative and right-skewed: a 10% price cut moves a 90-unit rush hour
far more in absolute terms than a 5-unit dead hour. Plain RMSE would let the busy
hours dominate the loss and the model would simply ignore quiet ones. We fit in log
space, then convert back to units before scoring, so the reported RMSE is still in
real units that a business can read.
"""
import json
import time

import joblib
import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import (ExtraTreesRegressor, GradientBoostingRegressor,
                              HistGradientBoostingRegressor,
                              RandomForestRegressor)
from sklearn.linear_model import Ridge
from sklearn.metrics import make_scorer, r2_score, root_mean_squared_error
from sklearn.model_selection import GridSearchCV
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from config import MODEL_DIR, OUTPUT_DIR, RAW_CSV, SEED, TARGET
from features import (CATEGORICAL, FEATURES, NUMERIC, chronological_split,
                      expanding_window_cv, load)

# n_jobs=-1 spawns one worker per core, and each worker holds its own copy of the
# data plus a full forest. On a laptop that is an out-of-memory crash, not speed.
# Cap it, and let the forest itself stay single-threaded inside each worker.
N_JOBS = 2


def rmse_units(y_true_log, y_pred_log):
    """Score in real units even though the model is fitted in log space."""
    return root_mean_squared_error(
        np.expm1(y_true_log), np.clip(np.expm1(y_pred_log), 0, None))


UNIT_RMSE = make_scorer(rmse_units, greater_is_better=False)


def preprocessor():
    return ColumnTransformer([
        ("num", StandardScaler(), NUMERIC),
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL),
    ])


# Ridge IS linear regression, with an L2 penalty. Plain OLS on ~40 correlated features
# (log_price and competitor_price_ratio move together by construction) produces wildly
# unstable coefficients, which would make the elasticity read-out meaningless.
CANDIDATES = {
    "linear_regression": (
        Ridge(random_state=SEED),
        {"model__alpha": [0.01, 0.1, 1.0, 10.0, 100.0]},
    ),
    "random_forest": (
        RandomForestRegressor(n_estimators=250, random_state=SEED, n_jobs=1),
        {
            "model__max_depth": [10, 20, None],
            "model__min_samples_leaf": [1, 5, 20],
            "model__max_features": ["sqrt", 0.5],
        },
    ),
    "extra_trees": (
        ExtraTreesRegressor(n_estimators=350, random_state=SEED, n_jobs=1),
        {
            "model__max_depth": [10, 20, None],
            "model__min_samples_leaf": [1, 5, 20],
            "model__max_features": ["sqrt", 0.5],
        },
    ),
    "hist_gradient_boosting": (
        HistGradientBoostingRegressor(random_state=SEED),
        {
            "model__max_depth": [4, 6],
            "model__learning_rate": [0.05, 0.08],
            "model__max_iter": [200, 300],
        },
    ),
    "gradient_boosting": (
        GradientBoostingRegressor(random_state=SEED),
        {
            "model__n_estimators": [200, 400],
            "model__learning_rate": [0.05, 0.1],
            "model__max_depth": [3, 5],
            "model__subsample": [0.8, 1.0],
        },
    ),
}


def main():
    df = load(RAW_CSV)
    train, test = chronological_split(df, test_frac=0.2)

    X_tr, y_tr = train[FEATURES], np.log1p(train[TARGET])
    X_te, y_te = test[FEATURES], test[TARGET]

    print(f"train {len(train):,} rows  {train.timestamp.min()} .. {train.timestamp.max()}")
    print(f"test  {len(test):,} rows  {test.timestamp.min()} .. {test.timestamp.max()}"
          f"   (never seen)\n")

    cv = list(expanding_window_cv(train))
    print(f"{len(cv)} expanding-window CV folds: {[(len(a), len(b)) for a, b in cv]}\n")

    results, fitted = {}, {}
    for name, (estimator, grid) in CANDIDATES.items():
        n_fits = np.prod([len(v) for v in grid.values()]) * len(cv)
        print(f"--- {name}  ({int(n_fits)} fits) ---")
        t0 = time.time()

        gs = GridSearchCV(
            Pipeline([("pre", preprocessor()), ("model", estimator)]),
            grid, cv=cv, scoring=UNIT_RMSE, n_jobs=N_JOBS,
            pre_dispatch="2*n_jobs", refit=True,
        )
        gs.fit(X_tr, y_tr)

        pred = np.clip(np.expm1(gs.predict(X_te)), 0, None)
        results[name] = {
            "cv_rmse": float(-gs.best_score_),
            "test_rmse": float(root_mean_squared_error(y_te, pred)),
            "test_r2": float(r2_score(y_te, pred)),
            "best_params": {k: str(v) for k, v in gs.best_params_.items()},
            "fit_seconds": round(time.time() - t0, 1),
        }
        fitted[name] = gs.best_estimator_

        r = results[name]
        print(f"    CV RMSE {r['cv_rmse']:.3f} | TEST RMSE {r['test_rmse']:.3f}  "
              f"R2 {r['test_r2']:.4f}   [{r['fit_seconds']}s]")
        print(f"    best: {gs.best_params_}\n")

    # Select on CV, never on the test score. Choosing the model that happens to win on
    # the test set is how you fool yourself and then fool an interviewer.
    winner = min(results, key=lambda k: results[k]["cv_rmse"])

    baseline = np.full(len(y_te), train[TARGET].mean())
    base_rmse = root_mean_squared_error(y_te, baseline)

    print("=" * 64)
    print(f"WINNER (by CV RMSE): {winner}")
    print(f"Baseline (predict mean demand): RMSE {base_rmse:.3f}  "
          f"R2 {r2_score(y_te, baseline):.4f}")
    print(f"Improvement over baseline: "
          f"{(1 - results[winner]['test_rmse'] / base_rmse) * 100:.1f}%")
    print("=" * 64)

    for name, est in fitted.items():
        joblib.dump(est, MODEL_DIR / f"{name}.pkl")
    joblib.dump({"model": fitted[winner], "name": winner, "features": FEATURES},
                MODEL_DIR / "pricing_model.pkl")

    (OUTPUT_DIR / "model_comparison.json").write_text(json.dumps(
        {"results": results, "winner": winner, "baseline_rmse": float(base_rmse)},
        indent=2))
    print(f"\nSaved -> {MODEL_DIR / 'pricing_model.pkl'}")


if __name__ == "__main__":
    main()
