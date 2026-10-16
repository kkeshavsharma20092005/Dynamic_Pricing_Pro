import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_pipeline"))

import joblib
import numpy as np
import pandas as pd

from config import METRICS_JSON, MODEL_PKL, PRODUCTS, RAW_CSV, TARGET
from features import FEATURES, engineer, load

GRID_POINTS = 121


def apply_log_smearing(log_pred: np.ndarray, residual_variance: float) -> np.ndarray:
    """Convert log-scale predictions back to units with a smearing correction."""
    return np.clip(np.expm1(log_pred) * np.exp(0.5 * residual_variance), 0, None)


class PricingEngine:
    def __init__(self):
        bundle = joblib.load(MODEL_PKL)
        self.model = bundle["model"]
        self.model_name = bundle["name"]

        # Recent history supplies the demand lags. These are legitimate inputs: when
        # you set the next hour's price, last hour's sales are already a fact. The API
        # caller should not have to know them, so we look them up per product.
        hist = pd.read_csv(RAW_CSV, parse_dates=["timestamp"])
        self.lags = (hist.sort_values("timestamp")
                         .groupby("product_id")
                         .agg(demand_lag_1h=("units_sold", "last"),
                              demand_lag_24h=("units_sold", "last"),
                              demand_roll_24h=("units_sold", lambda s: s.tail(24).mean()),
                              time_index=("units_sold", "size"))
                         .to_dict("index"))
        self.products = sorted(hist.product_id.unique())
        self.log_residual_variance = self._estimate_log_residual_variance()

    def _estimate_log_residual_variance(self) -> float:
        """Estimate the residual variance in log-space so back-transformed demand is unbiased."""
        df = load(RAW_CSV)
        log_y = np.log1p(df[TARGET])
        pred_log = self.model.predict(df[FEATURES])
        variance = float(np.var(log_y - pred_log, ddof=1))
        return max(variance, 1e-6)

    # ------------------------------------------------------------------ context
    def build_context(self, req) -> pd.Series:
        """Turn a validated API request into one raw row the feature layer can chew."""
        spec = PRODUCTS.get(req.product_id)
        if spec is None:
            raise KeyError(f"Unknown product_id '{req.product_id}'. "
                           f"Known: {', '.join(self.products)}")

        lag = self.lags.get(req.product_id, {})
        price = req.current_price if req.current_price is not None else spec["base_price"]
        cost = req.unit_cost if req.unit_cost is not None else spec["cost"]

        if cost >= price:
            raise ValueError(
                f"unit_cost ({cost:.2f}) is not below the price being optimised "
                f"({price:.2f}). No pricing model can rescue a loss-making unit.")

        return pd.Series({
            "product_id": req.product_id,
            "our_price": float(price),
            "unit_cost": float(cost),
            "hour": int(req.hour),
            "day_of_week": int(req.day_of_week),
            "month": int(req.month),
            "is_weekend": int(req.day_of_week >= 5),
            "is_holiday": int(req.is_holiday),
            "temperature": float(req.temperature),
            "precipitation": float(req.precipitation),
            "weather_condition": req.weather_condition.value,
            "competitor_1_price": float(req.competitor_1_price),
            "competitor_2_price": float(req.competitor_2_price),
            "competitor_3_price": float(req.competitor_3_price),
            "demand_lag_1h": float(lag.get("demand_lag_1h", 20)),
            "demand_lag_24h": float(lag.get("demand_lag_24h", 20)),
            "demand_roll_24h": float(lag.get("demand_roll_24h", 20)),
            "time_index": float(lag.get("time_index", 0)),
        })

    # ------------------------------------------------------------------ inference
    def predict_demand(self, ctx: pd.Series, prices: np.ndarray) -> np.ndarray:
        """
        Demand at each candidate price. ONE batched model call, always.

        `pd.DataFrame([ctx] * n)` builds n Series and concatenates them - fine for 2
        rows, wasteful for 121, and it runs on every slider drag. Broadcasting a dict
        of scalars into columns is the same result an order of magnitude cheaper.
        """
        n = len(prices)
        cand = pd.DataFrame({k: np.repeat(v, n) for k, v in ctx.items()})
        cand["our_price"] = prices

        # Re-derive EVERY price-dependent feature for each candidate. Change the price
        # but leave competitor_price_ratio stale and you are scoring a row that cannot
        # exist - the model returns a confident fiction and the optimiser climbs it.
        X = engineer(cand)[FEATURES]
        log_pred = self.model.predict(X)
        return apply_log_smearing(log_pred, self.log_residual_variance)

    @staticmethod
    def elasticity_from_curve(prices: np.ndarray, demand: np.ndarray,
                              i: int, eps=0.05) -> float:
        """
        Read elasticity straight off the curve we already computed.

        The old version fired an ENTIRE extra model call to probe two nearby prices -
        a third of total request latency spent recomputing points that were already
        sitting in `demand`. The grid is dense, so a central difference over a ~5%
        stencil gives the same number for free.
        """
        step = max(1, int(round(eps * len(prices) / 2)))
        lo, hi = max(0, i - step), min(len(prices) - 1, i + step)
        if lo == hi:
            return 0.0

        q_lo, q_hi = np.clip([demand[lo], demand[hi]], 0.01, None)
        p_lo, p_hi = prices[lo], prices[hi]

        pct_dq = (q_hi - q_lo) / ((q_hi + q_lo) / 2)
        pct_dp = (p_hi - p_lo) / ((p_hi + p_lo) / 2)
        return float(pct_dq / pct_dp) if pct_dp else 0.0

    # ------------------------------------------------------------------ optimise
    def recommend(self, req) -> dict:
        ctx = self.build_context(req)
        current_price = float(ctx["our_price"])
        cost = float(ctx["unit_cost"])
        max_change = req.max_change_pct / 100.0

        # GUARDRAILS. Unconstrained, an optimiser will walk into a price region the
        # model has never seen and report a confident fantasy. Two hard limits:
        #   - never below cost (selling at a loss is not an optimisation)
        #   - never more than max_change from today's price
        lo = max(current_price * (1 - max_change), cost * 1.01)
        hi = current_price * (1 + max_change)
        grid = np.linspace(lo, hi, GRID_POINTS)

        # ONE model call for everything. The current price rides along as the last
        # element of the same batch instead of costing a second round trip through
        # the pipeline, and elasticity is read off the curve instead of a third.
        batch = np.append(grid, current_price)
        all_demand = self.predict_demand(ctx, batch)
        demand, now_demand = all_demand[:-1], float(all_demand[-1])

        revenue = grid * demand
        profit = (grid - cost) * demand

        objective = revenue if req.objective == "revenue" else profit
        best_i = int(np.argmax(objective))
        best_price = float(grid[best_i])

        now_revenue = current_price * now_demand
        now_profit = (current_price - cost) * now_demand

        e = self.elasticity_from_curve(grid, demand, best_i)
        guardrail_hit = abs(abs(best_price / current_price - 1) - max_change) < 1e-3

        # ASCII only. These strings cross a JSON boundary and get printed to consoles
        # (Windows cp1252 cannot encode a proportional-to sign, and the whole request
        # dies on the encode, not on anything to do with pricing).
        warning = None
        if guardrail_hit:
            warning = (
                f"Hit the +/-{req.max_change_pct:.0f}% guardrail - this is a boundary, "
                f"not a true optimum. Read it as a direction, not a precise price."
            )
        if req.objective == "revenue" and e < -1:
            warning = (
                "Revenue-maximisation with elastic demand (|e| > 1) is degenerate: "
                "revenue is proportional to P^(1+e), which RISES as price falls, so "
                "this will always recommend the lowest legal price. Use 'profit'."
            )
        if e >= 0:
            warning = (
                "Elasticity is non-negative - the model believes raising price SELLS "
                "MORE. That is confounding, not a goldmine. Do not act on this."
            )

        def lift(new, old):
            return (new / old - 1) * 100 if old > 0 else 0.0

        return {
            "product_id": req.product_id,
            "objective": req.objective,
            "current_price": round(current_price, 2),
            "recommended_price": round(best_price, 2),
            "price_change_pct": round((best_price / current_price - 1) * 100, 2),
            "current_demand": round(now_demand, 2),
            "recommended_demand": round(float(demand[best_i]), 2),
            "current_revenue": round(now_revenue, 2),
            "recommended_revenue": round(float(revenue[best_i]), 2),
            "revenue_lift_pct": round(lift(float(revenue[best_i]), now_revenue), 2),
            "current_profit": round(now_profit, 2),
            "recommended_profit": round(float(profit[best_i]), 2),
            "profit_lift_pct": round(lift(float(profit[best_i]), now_profit), 2),
            "elasticity": round(e, 3),
            "elasticity_label": (
                "Elastic — price-sensitive" if e < -1
                else "Inelastic — room to raise" if e < 0
                else "BROKEN — positive elasticity"),
            "unit_cost": round(cost, 2),
            "guardrail_hit": guardrail_hit,
            "warning": warning,
            # Downsample the curve for the chart: 121 points is more than any line
            # chart needs, and the payload is sent on every slider drag.
            "curve": [
                {"price": round(float(p), 2), "demand": round(float(d), 2),
                 "revenue": round(float(r), 2), "profit": round(float(pr), 2)}
                for p, d, r, pr in zip(grid[::3], demand[::3], revenue[::3], profit[::3])
            ],
        }
