# Dynamic Pricing Optimization Engine

A production-shaped pricing system: it predicts demand from **price, competitor position,
time and weather**, then searches for the price that maximises profit — and serves that
over a REST API and a live dashboard.

**Stack:** Pandas · NumPy · Scikit-Learn · GridSearchCV · FastAPI · Pydantic · Tailwind · Chart.js

---

## The core idea

**You cannot train a model to predict "the optimal price."** No such label exists —
historical prices were not optimal, so a model fitted to them would only learn to repeat
past mistakes. So the system splits in two:

1. **A demand model (ML)** answers one question: *at price P, in this context, how many units?*
2. **An optimizer (plain arithmetic)** sweeps 121 candidate prices, asks the model that
   question for each, and returns the price maximising `(price − cost) × demand`.

Step 2 is a grid search over a curve. That is the entire pricing engine, and it is
deliberately *not* machine learning — it is arithmetic you can audit.

---

## Results

Chronological holdout (last 20% of hours, never seen in training or tuning).

| Model | RMSE | R² | vs. baseline | Elasticity | Recovers truth? | |
|---|---|---|---|---|---|---|
| **Linear Regression (Ridge)** | **6.80** | **0.924** | **+76.7%** | **−1.91** | ✅ err 0.12 | **selected** |
| Gradient Boosting | 8.17 | 0.891 | +72.0% | −1.47 | ✅ err 0.32 | |
| Random Forest | 10.80 | 0.809 | +63.1% | −0.59 | ❌ err 1.20 | **rejected** |
| Baseline (mean demand) | 29.23 | −0.401 | — | — | — | |

### The result that matters most

**Random Forest scores a respectable R² of 0.81 and is still useless for pricing.**

Its estimated elasticity is **−0.59** when the truth is **−1.79**. It forecasts demand well
by leaning on `demand_lag_1h`, while barely responding to price. Ship it on RMSE alone and
your optimizer climbs a nearly flat curve — it would systematically under-correct prices
while your dashboard displayed a healthy R².

**So models are gated on elasticity, not RMSE.** A model that cannot reliably produce a
downward-sloping demand curve is rejected regardless of how well it forecasts. Random
Forest sloped downward on only 89% of rows (threshold: 90%).

### Ground-truth validation — the whole point of synthetic data

The generator builds demand from a *known* elasticity that the model is never shown. So
unlike with real data, we can check whether the estimator is actually right.

Elasticity is not one number — it varies by context, and **that variation is the entire
justification for dynamic pricing**:

| Segment | Estimated | True | Error |
|---|---|---|---|
| Rush hour (07–09, 17–19) | −1.63 | −1.54 | 0.08 |
| Off-peak (22–05) | −2.09 | −2.07 | 0.02 |
| Raining | −1.67 | −1.59 | 0.08 |
| Dry | −1.99 | −1.96 | 0.03 |

**Per-row correlation with ground truth: r = 0.870, MAE = 0.134.**

The model discovered on its own that *commuters in the rain barely look at price* — which
is precisely the surge opportunity a static price leaves on the table. It was never told.

---

## Three traps baked into the data on purpose

**1. Endogeneity — the trap that ruins most pricing projects.**
Real businesses surge-price: they raise prices exactly when demand is high. Price then
correlates with the unobserved demand drivers, and a naive regression reads the correlation
backwards. Measured on this data:

| Estimator | Elasticity | Error vs. truth (−1.79) |
|---|---|---|
| Naive log-log regression | **−0.49** | 1.30 ❌ |
| Controls, *wrong* functional form | −1.51 | 0.28 |
| Controls, correct functional form | **−1.92** | 0.13 ✅ |

Note the middle row. Including a confounder with the **wrong shape** still leaves bias:
temperature affects demand *quadratically* (comfort peaks near 21°C), and modelling it
linearly costs 0.28 of elasticity. This is why `features.py` encodes `temp_comfort` as a
curve and time as sine/cosine pairs rather than raw integers.

**2. Identification.** If price were a pure function of the demand drivers, elasticity would
be mathematically unrecoverable. Real firms run promos and price tests; the generator injects
that same exogenous variation, because without it no model could find the curve.

**3. Count noise.** Demand is drawn from a Poisson, so variance scales with the mean — like
real sales, not like a smooth line plus Gaussian noise.

---

## How the cross-features drive pricing decisions

| Feature | What it does to the engine |
|---|---|
| **`competitor_price_ratio`**<br>`our_price / competitor_min_price` | The decisive feature. Customers don't judge \$24 in the abstract — they judge it against the cheapest option on screen. Raw price cannot express "we are 8% over the cheapest rival," and *that ratio*, not the dollar amount, is what collapses demand. When the engine sweeps candidate prices, this is what moves, and its slope **is** the curve the optimizer climbs. |
| **`weather_demand_index`** | Compresses temperature + rainfall into one "how much does the world want this right now" signal. It is a **demand shifter**, not a price term: it moves the curve *up*, without changing its slope. Practical effect: on a rainy rush-hour evening the whole curve lifts, so the profit-maximising price rises — **the model surges, and can explain why.** |
| **`hour_sin` / `hour_cos`** | Hour 23 and hour 0 are one hour apart, but 23 apart as integers. Feed the integer and a linear model believes midnight is maximally distant from 11pm, so it cannot learn the twin commuter peaks. The sine/cosine pair puts the clock back on a circle. Without this the model mis-times **every** surge window. |
| **`rush_x_logprice`**<br>**`rain_x_logprice`** | These make **elasticity itself** context-dependent. In a log-demand model the coefficient on `log_price` *is* the elasticity — so a coefficient on `rush × log_price` is literally "how much rush hour shifts the elasticity." Without them a linear model fits one global slope and the premise of *dynamic* pricing collapses. **These are what produced the −1.63 vs −2.09 split in the table above.** |

### Observed effect end-to-end

| Scenario | Recommended | Change | Elasticity | Why |
|---|---|---|---|---|
| Rush-hour **storm** | \$31.20 | **+30%** | −1.13 | Demand shifted up, customers insensitive → **surge** |
| Dead **3am**, clear | \$20.04 | **−16.5%** | −1.92 | Demand shifted down, customers shopping → **discount** |
| Rivals **undercut 25%** | \$25.08 | +4.5% | −1.62 | Ratio worsens; the engine holds back |

---

## Why revenue-maximisation is a trap (and profit is the default)

Demand here is **elastic** (|e| > 1). For any elastic product, `revenue ∝ P^(1+e)`, which
**rises monotonically as price falls**. So a revenue-maximising optimizer recommends the
lowest legal price, forever — it has no interior optimum. Observed: with `objective=revenue`
the engine slams into the −30% guardrail every time.

Profit has a cost floor, so it has a genuine peak. `objective` defaults to `profit`, and the
API returns an explicit warning if you ask for `revenue` on elastic demand.

---

## Run it

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on Unix)
pip install -r requirements.txt

python data_pipeline/generate_data.py   # 8,760 rows + prove the traps are armed
python data_pipeline/train.py           # 3 models x GridSearchCV, time-aware CV
python data_pipeline/evaluate.py        # RMSE / R2 / elasticity / ground-truth recovery

uvicorn backend.main:app --reload       # -> http://127.0.0.1:8000
python backend/test_api.py              # end-to-end API tests
```

- Dashboard → <http://127.0.0.1:8000/>
- OpenAPI docs → <http://127.0.0.1:8000/docs>

### API

```bash
curl -X POST http://127.0.0.1:8000/predict/ \
  -H "Content-Type: application/json" \
  -d '{"product_id":"SKU-URBAN-RIDE","hour":18,"day_of_week":2,"month":4,
       "temperature":12,"precipitation":14,"weather_condition":"Stormy",
       "competitor_1_price":24,"competitor_2_price":25.2,"competitor_3_price":23.3}'
```

`GET /metrics/` returns RMSE, R², elasticity, ground-truth recovery error, and feature
importances.

---

## Layout

```
data_pipeline/
  config.py         ground-truth constants, paths, SKU definitions
  generate_data.py  8,760 hourly rows; endogeneity + identification + count noise
  features.py       cross-features, cyclical encodings, ONE split definition
  train.py          Pipeline + GridSearchCV across 3 model families
  evaluate.py       RMSE, R2, elasticity, permutation importance, truth recovery
backend/
  schemas.py        Pydantic contracts + input validation
  engine.py         price grid -> predict demand -> argmax profit
  main.py           FastAPI app, /predict/ /metrics/ /products/ /health/
  test_api.py       end-to-end tests incl. 7 input-validation cases
frontend/
  index.html        Tailwind + Chart.js dashboard, live sliders, presets
```

### Engineering details that matter

**`features.engineer()` is imported by training *and* by the live API.** When the engine asks
"what if I charged \$26 instead of \$24?", every price-derived feature
(`competitor_price_ratio`, `log_price`, `margin_pct`, the interactions) is recomputed for the
new price. Swapping `our_price` while leaving the ratios stale would score a row that
**cannot exist** — the model returns a confident fiction and the optimizer climbs a fake curve.

**Cross-validation splits on time, not row position.** This is panel data: 3 SKUs share every
timestamp. `TimeSeriesSplit` cuts on row index, which would tear a single hour across a fold
boundary and train on one SKU's 3pm while testing another's. The custom splitter keeps every
fold an honest past → future test.

**Preprocessing lives inside the `Pipeline`.** Fit the scaler on the full dataset first and
you have leaked test-set statistics into training; every metric afterwards is inflated.

**Guardrails on the optimizer.** Never below cost, never more than ±N% from today's price.
An unconstrained optimizer will walk into a price region the model has never seen and report
a confident fantasy. The API flags `guardrail_hit` when the recommendation is a boundary
rather than a true optimum.

---

## Deploy — Render (free tier, kept awake 24/7)

### 1. Push to GitHub

```bash
gh repo create dynamic-pricing-engine --public --source=. --push
# or, without the gh CLI:
git remote add origin https://github.com/<you>/dynamic-pricing-engine.git
git push -u origin main
```

### 2. Deploy on Render

Go to <https://dashboard.render.com/blueprints> → **New Blueprint Instance** → pick the
repo. Render reads `render.yaml`, sees `runtime: docker`, and builds the `Dockerfile`.
Nothing to configure by hand.

*(Or: **New → Web Service** → connect the repo → Runtime **Docker** → Instance Type
**Free**.)*

Build takes ~3–5 minutes. Your dashboard lands at
`https://dynamic-pricing-engine.onrender.com`.

### 3. Keep it awake 24/7

**Render's free tier sleeps after 15 minutes of inactivity**, and the cold start is ~50
seconds — long enough that a recruiter clicking your link assumes the site is broken and
leaves. Fix it with a free uptime monitor:

1. [cron-job.org](https://cron-job.org) (free) → **Create cronjob**
2. URL: `https://<your-app>.onrender.com/health/`
3. Schedule: **every 10 minutes**

That's exactly what `/health/` exists for — it returns a 43-byte JSON and never touches the
model, so the ping costs essentially nothing.

**Never point a keep-alive at `/predict/`.** That runs inference on every call and would
burn your compute allowance on requests nobody made.

**The arithmetic works out.** Render's free tier grants 750 instance-hours/month; a month
is ~730 hours. So *one* service pinged around the clock fits inside the allowance with room
to spare. A second always-on free service would not.

### What is and isn't committed

Only the **selected** model (6.7 KB) ships. `random_forest.pkl` is **105 MB** — past
GitHub's hard 100 MB limit, and it would break the push outright. It's reproducible from a
seeded pipeline, so it's gitignored. Artifacts you can rebuild don't belong in git.

The Dockerfile deliberately does **not** retrain at build time: a full GridSearchCV run
takes ~8 minutes and would blow past the free-tier build timeout. It fails loudly if the
committed model is missing, rather than booting a server that 500s on every request.

**The Dockerfile binds to `$PORT`, not a hard-coded port.** Render injects `$PORT` at
runtime and routes to it; hard-coding a port is the single most common reason a Render
deploy builds successfully and then 502s forever.

---

## Honest limitations

- **The data is synthetic.** That is a deliberate trade: it buys hourly granularity and a
  known ground truth (so the estimator can be *validated*), at the cost of real-world messiness.
  A real-data version of this project — including the data-quality forensics on a genuine
  Olist retail set — is the companion piece.
- **Linear regression winning is partly an artifact.** The generator builds demand from a
  log-linear equation, and we fit in log space, so the linear model is *correctly specified*.
  Trees must approximate a smooth surface with step functions and lose. **On real data this
  frequently flips** — do not generalise "linear beats trees" from this.
- **The lift figure is a model belief, not a measurement.** The only way to know the true
  effect is an A/B test against the current pricing rule. Never present it as realised revenue.
- **CORS is wide open** (`allow_origins=["*"]`) for the demo. Lock it down before deploying.
