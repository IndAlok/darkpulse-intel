# DarkPulse

DarkPulse is a production-grade localized dark web intelligence monitor built for law-enforcement investigators. It sweeps indexed onion sites, underground forums, public digital marketplaces, and approved public Telegram channels, detects localized trafficking indicators, decodes evolving multilingual slang, geo-localizes activity to Surat neighborhoods, profiles vendors and actors with relationship graphs, and surfaces actionable, traceable, severity-scored intelligence with tamper-evident evidence sealing.

## Table of Contents

1. [Architecture](#architecture)
2. [Features](#features)
3. [Quick Start](#quick-start)
4. [Configuration](#configuration)
5. [API Reference](#api-reference)
6. [Deployment](#deployment)
7. [Safety and Ethics](#safety-and-ethics)
8. [Development](#development)
9. [Troubleshooting](#troubleshooting)

## Architecture

```
SOURCES                          PIPELINE                          INVESTIGATORS
─────────────────────            ──────────────────────────        ─────────────────────
Historical datasets   ──▶  Collection → Safety gate → Hash →       React dashboard
Public Telegram       ──▶  Contract 1 → MongoDB (pending) →        (trends, graph, map,
Approved surface      ──▶  processor → NLP (slang, NER,             alerts, reports)
Reviewed onion seeds  ──▶  intent, geo, severity) → Contract 2 →   │
                            MongoDB + Neo4j                         ▼
                            → API + alerts + evidence sealing      API on :8003
```

The system is a single unified Python service with four functional layers:

| Layer | Location | Responsibility |
|-------|----------|----------------|
| Ingestion | `src/darkpulse/ingestion/` | Collectors, historical loaders, pre-publish safety gate, hashing, deduplication, Contract 1 persistence |
| NLP | `src/darkpulse/nlp/` | Sanitization, language detection, slang decoding, NER, intent, geo, actor links, severity |
| Storage | `src/darkpulse/storage/` | MongoDB (including full-text search) and Neo4j connection managers |
| API | `src/darkpulse/api/` | FastAPI investigator API, evidence sealing, export |

Data flows through two frozen contracts:

- **Contract 1 (RawIngest)** - `contracts/contract1-raw-ingest.schema.json`. Produced by ingestion, consumed by the NLP pipeline and storage.
- **Contract 2 (TraffickingIntel)** - `contracts/contract2-intel.schema.json`. Produced by NLP, consumed by storage and the API.
- **Contract 3 (Investigator API)** - `contracts/contract3-api.openapi.yaml`. Served to the frontend.

Every artifact carries a `trace_id` threaded from capture through processing to the API.

## Features

- **Multi-source ingestion** - Evolution and Gwern historical datasets, approved public Telegram channels, approved surface sites, and reviewed onion seeds with bounded crawl policy.
- **Pre-publish safety gate** - prohibited media, blocked sources, and blocked content hashes are rejected in memory before anything is persisted.
- **Multilingual NLP** - Gujarati, Hindi, English, and code-mixed/romanized text, curated slang dictionary (200+ terms) plus embedding-based auto-discovery with analyst review.
- **Deterministic entity extraction** - Bitcoin, Ethereum, Monero, Litecoin, and Bitcoin Cash wallets, PGP fingerprints, Telegram/Wickr/Signal/email/phone contacts, prices and quantities.
- **Intent classification** - sale / solicitation / discussion / review / unrelated with rule-based and ML paths.
- **Geo-localization** - explicit, slang-based, ship-from, and inferred matching against a 44-neighborhood Surat gazetteer.
- **Actor profiling** - vendor aggregation, pseudonym-link hypotheses (username, PGP, wallet), activity timelines.
- **Relationship graph** - Neo4j with Vendor, Wallet, Product, Neighborhood, Market, and IntelRef nodes.
- **Severity scoring (TSI)** - explainable, factor-based, config-tunable with bands from info to critical.
- **Alerting** - configurable rules with severity/product/neighborhood filters, history, and WebSocket streaming.
- **Evidence sealing** - SHA-256 of final emitted bytes, optional RFC 3161 trusted timestamps, hash-chained ledger.
- **Investigator dashboard** - intel feed, trends, source ranking, neighborhood heatmap, actor graph, alerts, watchlists, slang dictionary, and sealed report export.

## Quick Start

### Prerequisites

- Docker Engine 24+ with Docker Compose v2
- 8 GB RAM recommended (16 GB for full NLP models)
- Python 3.11+ and Node 20+ only for local development

### Run the full stack

```bash
cd darkpulse
cp .env.example .env
# Set NEO4J_PASSWORD and GRAFANA_PASSWORD to real values

docker compose --profile core build
docker compose --profile core up -d
```

Services:

| Service | URL |
|---------|-----|
| Frontend | http://localhost:5173 |
| API | http://localhost:8003/api/v1 |
| API docs (Swagger) | http://localhost:8003/docs |
| Neo4j Browser | http://localhost:7474 |
| MongoDB | localhost:27017 |

### Load historical data

Place the Evolution dataset under `./data/evolution/market/` (listings.tsv, scrapes.tsv), then:

```bash
docker compose --profile loader up evolution-loader
```

Or run locally:

```bash
pip install -e ".[dev]"
python -m darkpulse.cli evolution --input data/evolution/market/listings.tsv --scrapes data/evolution/market/scrapes.tsv --limit 1000
```

### Verify the pipeline

```bash
# Intelligence stored
curl http://localhost:8003/api/v1/intel?limit=5

# Health
curl http://localhost:8003/api/v1/health
```

## Configuration

All configuration is via environment variables with the `DARKPULSE_` prefix (see `.env.example` for the complete list).

| Variable | Default | Purpose |
|----------|---------|---------|
| `DARKPULSE_ENVIRONMENT` | development | development or production (changes CORS) |
| `DARKPULSE_PROCESSOR_POLL_INTERVAL_SECONDS` | 2.0 | Raw-ingest processor poll interval |
| `DARKPULSE_REDIS_URL` | redis://localhost:16379/0 | Redis for dedup/checkpoints |
| `DARKPULSE_MONGODB_URI` | mongodb://localhost:27017 | MongoDB connection |
| `DARKPULSE_MONGODB_DATABASE` | darkpulse | MongoDB database |
| `DARKPULSE_NEO4J_URI` | bolt://localhost:7687 | Neo4j connection |
| `NEO4J_PASSWORD` | - | Neo4j password (required in production) |
| `DARKPULSE_SLANG_SEED_PATH` | data/slang_dictionary/seed_dictionary.txt | Curated slang dictionary |
| `DARKPULSE_RFC3161_ENABLED` | false | Enable RFC 3161 timestamp requests |
| `DARKPULSE_RFC3161_TSA_URL` | - | Trusted Timestamp Authority URL |
| `DARKPULSE_TELEGRAM_API_ID` | - | Telegram API ID (authorized collection only) |
| `DARKPULSE_TELEGRAM_API_HASH` | - | Telegram API hash (authorized collection only) |
| `DARKPULSE_TOR_PROXY_URL` | socks5://localhost:9050 | Tor SOCKS proxy for onion collection |

Severity weights are configurable via `DARKPULSE_SEVERITY_INTENT`, `DARKPULSE_SEVERITY_PRODUCT_HARM`, `DARKPULSE_SEVERITY_SOURCE_RELIABILITY`, `DARKPULSE_SEVERITY_LOCALIZATION`, `DARKPULSE_SEVERITY_RECENCY`, and `DARKPULSE_SEVERITY_EXPOSURE` (must sum to 1.0).

## API Reference

Interactive documentation is available at `/docs` (Swagger UI). All JSON responses use the envelope format:

```json
{
  "data": ...,
  "pagination": {"cursor": null, "limit": 50, "total": 0},
  "meta": {},
  "errors": []
}
```

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Service health |
| GET | `/api/v1/health` | Health with datastore + consumer status |
| GET | `/api/v1/intel` | Filtered intel feed (`product`, `neighborhood`, `severity_min`, `band`, `source_class`, `date_from`, `date_to`, `vendor`, `q`, `cursor`, `limit`) |
| GET | `/api/v1/intel/{id}` | Full intel detail |
| GET | `/api/v1/actors` | Actor/vendor list |
| GET | `/api/v1/actors/{id}` | Actor profile with timeline |
| GET | `/api/v1/graph` | Relationship graph (raw `{nodes, edges}`, `node_type` filter) |
| POST | `/api/v1/auth/login` | Exchange an access token for `{subject, role}` |
| GET | `/api/v1/auth/me` | Current principal |
| GET | `/api/v1/search` | Multilingual full-text search |
| GET | `/api/v1/dashboards/trends` | Activity trends (`7d`, `30d`, `90d`) |
| GET | `/api/v1/dashboards/sources` | Source ranking |
| GET | `/api/v1/dashboards/geo` | Neighborhood heatmap |
| GET/POST | `/api/v1/watchlists` | Watchlist CRUD |
| GET/POST | `/api/v1/slang` | Slang dictionary CRUD |
| GET | `/api/v1/slang/candidates` | Auto-discovered slang candidates |
| POST | `/api/v1/slang/{id}/approve` | Approve a discovered candidate |
| DELETE | `/api/v1/slang/{id}` | Delete a slang entry |
| GET/PUT | `/api/v1/alerts/config` | Alert rule configuration |
| GET | `/api/v1/alerts/history` | Alert history |
| GET | `/api/v1/export` | Export (`format=csv|json|pdf`, `intel_ids=...`) with sealed evidence |
| POST | `/api/v1/evidence/seal` | Seal an arbitrary payload |
| GET | `/api/v1/evidence/{hash}` | Inspect a ledger seal |
| GET | `/api/v1/evidence/verify` | Verify the hash-chained evidence ledger integrity |
| POST | `/api/v1/evidence/verify` | Verify a payload against a claimed seal hash |
| GET | `/api/v1/intel/{id}/evidence` | Governed evidence metadata for a record |
| GET | `/api/v1/operations/sources` | Approved source registry (admin) |
| GET | `/api/v1/operations/processing` | Raw ingest processing state (admin) |
| GET | `/api/v1/operations/onion-review` | Onion review posture (admin) |
| GET | `/api/v1/operations/audit` | Minimized audit log (admin) |
| GET | `/api/v1/operations/collection-runs` | Collector run history (admin) |
| PATCH | `/api/v1/alerts/history/{id}` | Acknowledge or assign an alert |
| WS | `/api/v1/alerts/ws` | Live alert stream |

## Deployment

### Docker Compose (recommended)

```bash
cp .env.example .env
# Set real passwords
docker compose --profile core build
docker compose --profile core up -d
```

Profiles:

| Profile | Services |
|---------|----------|
| `core` | Redis, MongoDB, Neo4j, backend, collector, frontend |
| `loader` | One-shot Evolution dataset loader |
| `tor` | Tor SOCKS proxy for reviewed onion collection |
| `observability` | Prometheus, Grafana |

### Railway

Production runs on Railway. The repository includes `railway.toml` and
`frontend/railway.toml`. The production architecture is backend, frontend,
collector (same backend image, `python -m darkpulse.cli collect-all --loop`),
MongoDB, and Redis, with Neo4j on AuraDB. The backend boots fail-closed in
production (auth, HTTPS frontend origin, and a non-default Neo4j password
are required). The frontend never publishes API tokens; investigators sign
in through `/auth/login`. Attach a Mongo volume of at least 1 GB (or set
WiredTiger cache ~0.25 on a 500 MB volume). Telegram and onion collection
stay CLI-gated. Historical `evolution` / `gwern` loads are one-shot jobs
when datasets are mounted. Set `PORT` explicitly (8080 backend, 5173
frontend) and use the template `MONGO_URL` for `DARKPULSE_MONGODB_URI`.

### Production checklist

1. Set `NEO4J_PASSWORD` and `GRAFANA_PASSWORD` to strong values.
2. Set `DARKPULSE_ENVIRONMENT=production` and `DARKPULSE_FRONTEND_ORIGIN`.
3. Mount an approved safety blocklist (blocked source prefixes, source hashes, content hashes) - the shipped policy has empty blocklists by design.
4. Configure `DARKPULSE_RFC3161_TSA_URL` if sealed exports must carry trusted timestamps.
5. Run the full test suite before deploying.
6. Keep live Telegram/onion collection disabled until written authorization and a reviewed source policy exist.

## Safety and Ethics

DarkPulse is an observe-only OSINT tool. The following rules are enforced in code:

- **No transacting.** The system never buys, messages targets, joins private sources, or authenticates into gated markets.
- **No de-anonymization.** Actor and pseudonym links are confidence-scored hypotheses for investigator confirmation - never asserted identities.
- **CSAM and prohibited media are hard-dropped** before persistence by the pre-publish safety gate and the NLP sanitizer (YARA rules, keyword patterns, and hash blocklists). Content-free audit events are emitted instead.
- **Data minimization.** Only public text is stored, binaries are rejected by default, raw records expire via TTL (24 h raw, 30 d alerts).
- **Evidence integrity.** Captures are SHA-256 hashed at the moment of capture, exports seal their canonical content bytes (the delivered file embeds the seal manifest and the hash is also returned in the `X-DarkPulse-Evidence-Seal` header) and are optionally RFC 3161 timestamped, the evidence ledger is hash-chained and verifiable through `/api/v1/evidence/verify`.

A report or export is not a claim of legal admissibility - authorization, procedure, and competent authority review determine that.

## Development

### Setup

```bash
cd darkpulse
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux/macOS
pip install -e ".[dev]"
```

### Tests

```bash
python -m pytest tests/ -v
```

### Frontend

```bash
cd frontend
npm ci
npm run lint
npm run test
npm run build
```

The frontend is a dark command-center: login, command palette, Recharts trends,
a force-directed graph with stable IDs, and a geographic Surat map. Tests use
Vitest + React Testing Library.

Public HTTPS collection loop:

```bash
python -m darkpulse.cli collect-all --loop --interval 300
```

### Project layout

```
├── src/darkpulse/
│   ├── api/          FastAPI routes, deps, app
│   ├── broker/       MongoDB-backed raw-ingest processor
│   ├── evidence/     Evidence sealing (RFC 3161, ledger)
│   ├── ingestion/    Collectors, loaders, safety, hashing, dedup, pipeline
│   ├── nlp/          Sanitizer, language, slang, NER, intent, geo, actors, severity
│   ├── storage/      MongoDB (search), Neo4j managers
│   ├── config.py     Unified settings
│   ├── models.py     Contract 1/2 models + API models
│   └── cli.py        Command-line ingestion tool
├── frontend/         React investigator dashboard
├── contracts/        JSON Schemas (source of truth)
├── safety/           Pre-publish safety policy
├── data/             Seed slang dictionary
├── scripts/          Model download, Gwern fetch, intent training
├── tests/            Python test suite
├── Dockerfile        Backend image (models preloaded at build)
├── frontend/Dockerfile
└── docker-compose.yml
```

### Model training

```bash
# Download NLP models (fastText LID, spaCy)
python scripts/download_models.py

# Fetch Gwern Grams/Kilos training data
python scripts/fetch_gwern_data.py

# Train the intent classifier
python scripts/train_intent.py
```

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `docker compose build` fails | Ensure you run from the repository root (the Dockerfile and compose file live there) |
| NLP logs "fasttext not available" | Run `python scripts/download_models.py` and set `DARKPULSE_FASTTEXT_LID_PATH` to the model location (the backend image preloads it at build time) |
| Frontend shows "API unavailable" | Confirm the backend is healthy: `curl http://localhost:8003/api/v1/health` |
| Telegram auth fails | Set `DARKPULSE_TELEGRAM_API_ID` and `DARKPULSE_TELEGRAM_API_HASH`, then run `python -m darkpulse.cli telegram-auth` |
| Evidence seal shows hash-only | `DARKPULSE_RFC3161_ENABLED` is false or no TSA URL configured, hash-only sealing is still valid integrity evidence |
| Ports already in use | All host ports are configurable via compose, adjust the left side of port mappings |
