# Dynamic Pricing Engine — container image.
# Runs on Render (free tier), Fly.io, Railway, or Hugging Face Spaces unchanged.
FROM python:3.11-slim

# Run as a non-root user. Render does not require this, but it is basic container
# hygiene, and it keeps the image portable to hosts that DO require it (Hugging Face
# Spaces executes containers as UID 1000 and will crash a root-owned app).
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    PYTHONUNBUFFERED=1

WORKDIR $HOME/app

# Dependencies in their own layer so Docker caches them. Code-only pushes then rebuild
# in seconds instead of re-downloading scikit-learn on every deploy.
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .

# Fail LOUDLY at build time if the model is missing, rather than booting a server that
# 500s on every request. We deliberately do NOT retrain here: a full GridSearchCV run
# takes ~8 minutes and would blow past the free-tier build timeout. The pipeline is
# seeded, so `python data_pipeline/train.py` reproduces this exact model locally.
RUN test -f models/pricing_model.pkl || \
    (echo "FATAL: models/pricing_model.pkl is missing from the repo." && exit 1)

# Render injects $PORT at runtime and expects the app to bind to it. Hard-coding a port
# is the single most common reason a Render deploy builds fine and then 502s forever.
# The default keeps the image working on hosts that don't inject one (HF uses 7860).
ENV PORT=7860
EXPOSE 7860

# Shell form, so ${PORT} is expanded at RUNTIME. In exec form (["uvicorn", ...]) the
# string "${PORT}" is passed through literally and uvicorn dies on startup.
#
# One worker on purpose: each worker loads its own copy of the model and scikit-learn.
# On Render's free 512 MB instance a second worker buys nothing and risks an OOM kill.
CMD uvicorn backend.main:app --host 0.0.0.0 --port ${PORT} --workers 1
