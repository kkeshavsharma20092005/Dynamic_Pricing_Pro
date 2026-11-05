
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Make this module import-safe however it is loaded: as `backend.main` by uvicorn, as
# `main` by the test client, or directly. Without the backend dir on sys.path,
# `uvicorn backend.main:app` cannot resolve `from engine import ...` at all.
_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent / "data_pipeline"))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import appdb
import kyc
import rides
from config import METRICS_JSON, MODEL_PKL, PRODUCTS
from engine import PricingEngine
from schemas import ModelMetrics, PredictRequest, PredictResponse

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

state: dict = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the model ONCE at startup, not per request. Deserialising a pipeline on
    # every call would add tens of milliseconds to a request that should take one.
    if not MODEL_PKL.exists():
        raise RuntimeError(
            f"No trained model at {MODEL_PKL}. Run the pipeline first:\n"
            f"  python data_pipeline/generate_data.py\n"
            f"  python data_pipeline/train.py\n"
            f"  python data_pipeline/evaluate.py")
    state["engine"] = PricingEngine()
    state["metrics"] = json.loads(METRICS_JSON.read_text())
    print(f"[startup] model '{state['engine'].model_name}' loaded, "
          f"{len(state['engine'].products)} products")

    rides.hub.engine = state["engine"]
    appdb.init_db()
    print(f"[startup] database: {appdb.backend_name()}")
    if appdb.backend_name() == "sqlite" and os.environ.get("RENDER"):
        print("[startup] WARNING: SQLite on Render's free disk is wiped on every restart. "
              "Set DATABASE_URL to a PostgreSQL database to keep accounts.")
    rides.cancel_interrupted_rides()
    created = appdb.ensure_admin()
    if created:
        print(f"[startup] admin account created: {created}  (shown only once)")
    yield
    state.clear()
    appdb.close()


app = FastAPI(
    title="Dynamic Pricing Optimization API",
    description=(
        "Predicts demand from price, competitor position, time and weather, then "
        "searches for the profit-maximising price."),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # demo only; lock this down for a real deployment
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(rides.router)
app.include_router(kyc.router)


@app.post("/predict/", response_model=PredictResponse, tags=["pricing"])
def predict(req: PredictRequest):
    """
    Recommend the optimal price for a real-time context.

    Pydantic has already rejected impossible inputs (negative price, hour 99). What
    remains are semantic failures - an unknown SKU, or a cost above the price - which
    are the caller's mistake, so they get a 4xx, not a 500.
    """
    try:
        return state["engine"].recommend(req)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:                                    # genuinely unexpected
        raise HTTPException(status_code=500, detail=f"Inference failed: {e}")


@app.get("/metrics/", response_model=ModelMetrics, tags=["model"])
def metrics():
    """Evaluation metrics, ground-truth recovery, and feature importances."""
    m = state["metrics"]
    sel = m["selected"]
    best = m["models"][sel]
    return {
        "selected_model": sel,
        "rmse": best["rmse"],
        "r2": best["r2"],
        "price_elasticity": best["price_elasticity"],
        "true_elasticity": m["true_elasticity"],
        "elasticity_recovery_error": best["elasticity_error_vs_truth"],
        "improvement_vs_baseline_pct": best["improvement_vs_baseline_pct"],
        "all_models": m["models"],
        "feature_importance": m["feature_importance"],
        "elasticity_by_segment": m["elasticity_by_segment"],
        "elasticity_row_correlation": m["elasticity_row_correlation"],
        "train_rows": m["train_rows"],
        "test_rows": m["test_rows"],
    }


@app.get("/products/", tags=["pricing"])
def products():
    """Known SKUs with their base price and cost, so the UI can prefill sensibly."""
    return [
        {"product_id": pid, "base_price": s["base_price"], "unit_cost": s["cost"]}
        for pid, s in PRODUCTS.items()
    ]


@app.get("/health/", tags=["ops"])
def health():
    return {"status": "ok", "model": state["engine"].model_name}


# ------------------------------------------------------------------ frontend
@app.middleware("http")
async def cache_policy(request, call_next):
    """
    Pages, styles and scripts must be re-checked on every load, or a browser keeps using
    an old stylesheet with new HTML after a deploy (a broken-looking page). Re-checking
    is cheap: an unchanged file answers 304 with no body. Photos change rarely, so a day.
    """
    response = await call_next(request)
    path = request.url.path
    if path.startswith("/static/photos/") or path.startswith("/static/icons/"):
        response.headers.setdefault("Cache-Control", "public, max-age=86400")
    elif not path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-cache")
    return response


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(FRONTEND / "home.html")

    @app.get("/ride", include_in_schema=False)
    def rider_app():
        return FileResponse(FRONTEND / "rider.html")

    @app.get("/driver", include_in_schema=False)
    def driver_app():
        return FileResponse(FRONTEND / "driver.html")

    @app.get("/admin", include_in_schema=False)
    def admin_app():
        return FileResponse(FRONTEND / "admin.html")

    @app.get("/dashboard", include_in_schema=False)
    def dashboard():
        return FileResponse(FRONTEND / "index.html")

    # A service worker can only control pages at or below its own path, so it must be
    # served from the root rather than from /static.
    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(FRONTEND / "sw.js", media_type="text/javascript")
