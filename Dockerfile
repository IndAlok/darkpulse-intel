FROM python:3.11-slim-bookworm AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml /build/pyproject.toml
COPY src /build/src
COPY contracts /build/contracts
COPY safety /build/safety
COPY data /build/data

WORKDIR /build

RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install --no-cache-dir --prefix=/install .

FROM python:3.11-slim-bookworm AS runtime

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system darkpulse \
    && adduser --system --ingroup darkpulse --home /nonexistent darkpulse

COPY --from=builder /install /usr/local
COPY src /app/src
COPY contracts /app/contracts
COPY safety /app/safety
COPY data /app/data
COPY config /app/config
COPY scripts /app/scripts

RUN mkdir -p /app/models /app/runtime && \
    chown -R darkpulse:darkpulse /app

RUN python /app/scripts/download_models.py

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV DARKPULSE_CONTRACT_PATH=/app/contracts/contract1-raw-ingest.schema.json
ENV DARKPULSE_SAFETY_POLICY_PATH=/app/safety/policy/prepublish-v1.json
ENV DARKPULSE_SLANG_SEED_PATH=/app/data/slang_dictionary/seed_dictionary.txt
ENV DARKPULSE_SOURCES_PATH=/app/config/sources.json
ENV DARKPULSE_ONION_REVIEW_POLICY_PATH=/app/config/onion-review.json
ENV DARKPULSE_FASTTEXT_LID_PATH=/app/models/lid.176.bin

USER darkpulse

EXPOSE 8080

CMD ["uvicorn", "darkpulse.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
