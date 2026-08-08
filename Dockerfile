# NOT VERIFIED ON THIS MACHINE. Docker was not installed on the build host and
# the user scoped containerisation out, so this image has never been built or
# run. It is provided because a deployment target needs one; treat it as a
# starting point, not a tested artifact. The verified path is the native one in
# the README.
#
# Multi-stage: the frontend bundle is built in Node and copied into the Python
# image, so the runtime carries no Node toolchain.

# ---- stage 1: frontend -----------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci || npm install
COPY web/ ./
RUN npm run build

# ---- stage 2: runtime ------------------------------------------------------
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/app/.cache/huggingface

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY eval/ eval/
COPY scripts/ scripts/
COPY skills/ skills/
COPY data/ data/
COPY reports/ reports/
COPY --from=web /web/dist web/dist

# Bake the embedding model and the index into the image so a cold container
# does not download weights on its first request.
RUN python scripts/validate_corpus.py && python scripts/build_index.py

RUN useradd --create-home --uid 10001 hazeready && chown -R hazeready:hazeready /app
USER hazeready

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
