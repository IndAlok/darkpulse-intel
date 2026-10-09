# DarkPulse

DarkPulse is an observe-only narcotics OSINT desk for investigators in Surat. The desk holds one corpus and does not partition records by case. It loads historical dark-market datasets and collects from sources an operator has explicitly approved: public HTTPS feeds, reviewed onion seeds over Tor, and authorized public Telegram channels. Each record is scored for trafficking intent, decoded for local slang, matched against 44 Surat neighborhoods, and linked to vendors in a relationship graph. Analysts can export selected records with a SHA-256 seal of the exact file they download.

The shipped `config/sources.json` enables no live source and `config/onion-review.json` approves no onion seed. Collection starts only after an operator adds and enables a reviewed source.

## Architecture

```
Historical datasets ─┐
Approved HTTPS feeds ─┼─▶ safety gate ─▶ hash + dedup ─▶ MongoDB raw_ingest (pending)
Reviewed onion seeds ─┤                                          │
Authorized Telegram ──┘                                          ▼
                         processor ─▶ NLP (slang, entities, intent, geo, severity)
                                           │
                               MongoDB intel + Neo4j graph + alerts
                                           │
                          FastAPI (container 8080, host 8003) ─▶ React desk (port 5173)
```

| Layer | Location | Responsibility |
|-------|----------|----------------|
| Ingestion | `src/darkpulse/ingestion/` | Collectors, historical loaders, pre-publish safety gate, hashing, dedup, Contract 1 writes |
| NLP | `src/darkpulse/nlp/` | Sanitizer, language detection, slang decoding, entity extraction, rule-based intent, geo, actor hypotheses, severity |
| Storage | `src/darkpulse/storage/` | MongoDB and Neo4j managers |
| API | `src/darkpulse/api/` | Investigator API, sessions, evidence sealing, export |

Contracts in `contracts/`: Contract 1 (`RawIngest`), Contract 2 (`TraffickingIntel`), and Contract 3 (the OpenAPI file the desk uses). `tests/test_openapi_contract.py` fails when Contract 3 and the live routes disagree.

## What it does

- **Ingestion.** Evolution and Gwern loaders, approved HTTPS feeds, reviewed onion seeds (bounded by page and depth limits), and authorized public Telegram channels. Unreviewed onion seeds and invite links are refused. `i2p` is a source-class value in the contracts. There is no i2p collector.
- **Safety gate.** Disallowed content types, oversized payloads, blocked source prefixes, and blocked SHA-256 hashes are rejected before anything is written. The shipped blocklists are empty; load a reviewed list for production.
- **NLP.** Gujarati, Hindi, English, and romanized text. A curated dictionary of 217 slang terms that analysts can extend or reject. Deterministic extraction of wallets, PGP fingerprints, contacts, prices, and quantities. Intent (sale, solicitation, discussion, review, unrelated) uses rules unless a trained model file is present. Text with intent `unrelated` and no product, slang, vendor, or wallet signal is dropped.
- **Actors.** Vendor aggregation and identity hypotheses from shared aliases, PGP fingerprints, and wallets. Hypotheses carry a confidence and are never asserted as identity.
- **Alerts.** Rules filter on severity, product, and neighborhood. Watchlists match whole words. Alerts stream over a WebSocket that takes a one-time ticket.
- **Evidence.** Exports are sealed with the SHA-256 of the downloaded bytes, returned in the `X-DarkPulse-Evidence-Seal` header. Each ledger entry stores the previous entry's hash, and `GET /api/v1/evidence/verify` checks those links. RFC 3161 timestamping is not implemented, and startup refuses `DARKPULSE_RFC3161_ENABLED=true`. Dedup and content-state TTLs are documented in `docs/evidence.md`.
- **Desk.** Intel feed with filters, search, trends, a neighborhood plot of the 44 gazetteer names (not a street map), the actor graph, alerts, watchlists, slang review, reports, and evidence. The system status page (`/operations`) is administrator-only.

## Quick start

Requires Docker Engine 24+ with Compose v2 and about 8 GB of RAM.

```bash
cd darkpulse-intel
cp .env.example .env
# Replace every CHANGE_ME value. Auth tokens must be at least 32 random characters.
docker compose --profile core up -d
```

`up` uses the existing images. Pass `--build` when those images are missing or stale.

| Service | Address |
|---------|---------|
| Desk | http://localhost:5173 |
| API | http://localhost:8003/api/v1 |
| Neo4j Browser | http://localhost:7474 |

Compose maps host port 8003 to container port 8080. The API process inside the container listens on 8080.

Sign in to the desk with a token from `DARKPULSE_AUTH_TOKENS_JSON`. `POST /api/v1/auth/login` is the only route that accepts that configured token. It returns an 8-hour session token. `POST /api/v1/auth/logout` revokes the session. Other routes accept only the session token.

Loopback open mode is the only unauthenticated path. Set `DARKPULSE_AUTH_ENABLED=false`, `DARKPULSE_LOCAL_OPEN_MODE=true`, and `DARKPULSE_API_HOST=127.0.0.1`, and run the API on the host. Requests from 127.0.0.1 are treated as administrator. Production refuses this mode.

### Load historical data

Place `listings.tsv` and `scrapes.tsv` under `./data/evolution/market/`, then:

```bash
docker compose --profile loader up evolution-loader
```

Loaders exit non-zero when the file is missing or every row is rejected.

### Demo corpus

`scripts/seed_demo.py` publishes synthetic observations so the desk has records to show. The API container root is read-only, so pipe the script in. The Compose container name is `darkpulse-backend-1`.

```bash
docker exec -i -e PYTHONPATH=/app/src darkpulse-backend-1 python - < scripts/seed_demo.py
```

```powershell
Get-Content -Raw scripts\seed_demo.py | docker exec -i -e PYTHONPATH=/app/src darkpulse-backend-1 python -
```

### Check health

```bash
curl http://localhost:8003/health          # liveness, always {"status": "ok"}
curl http://localhost:8003/api/v1/health   # readiness: 503 if MongoDB, Neo4j, or the processor is down
```

The readiness body also reports the latest collector run; `never_run` marks the overall status `degraded` without failing readiness.

## Configuration

Every setting is an environment variable; `.env.example` lists all of them with host-side values. Compose overrides the datastore URLs with in-network service names.

| Variable | Purpose |
|----------|---------|
| `DARKPULSE_AUTH_ENABLED`, `DARKPULSE_AUTH_TOKENS_JSON` | Required unless loopback open mode is set |
| `DARKPULSE_LOCAL_OPEN_MODE` | Loopback-only development mode; refused in production |
| `REDIS_PASSWORD`, `MONGO_ROOT_PASSWORD`, `NEO4J_PASSWORD` | Datastore credentials; Compose refuses to start without them |
| `DARKPULSE_RAW_RETENTION_DAYS` | Days completed or dropped raw records are kept (pending and failed records are never expired) |
| `DARKPULSE_PROCESSOR_*` | Processor poll interval, lease, and attempts |
| `DARKPULSE_SEVERITY_*` | Severity weights; startup fails unless they sum to 1.0 |
| `DARKPULSE_TOR_PROXY_URL` | Tor SOCKS proxy (`socks5://tor:9050` in Compose) |
| `DARKPULSE_TELEGRAM_API_ID`, `DARKPULSE_TELEGRAM_API_HASH` | Authorized Telegram collection only |
| `COLLECT_INTERVAL` | Seconds between `collect-all` cycles |

In production (`DARKPULSE_ENVIRONMENT=production`) startup also requires an HTTPS frontend origin and TLS on non-local MongoDB and Redis URLs.

A login session lasts 8 hours. The API keeps it in process memory and copies it to Redis when Redis is reachable. Logout deletes it. WebSocket tickets are single-use and expire after 60 seconds.

## Deployment

| Compose profile | Services |
|-----------------|----------|
| `core` | Redis, MongoDB, Neo4j, backend, collector, frontend |
| `loader` | One-shot Evolution loader |
| `tor` | Tor SOCKS proxy for reviewed onion seeds |
| `observability` | Prometheus (scrapes the backend's internal metrics port 9100) and Grafana |

Railway uses `railway.toml` (API, health check on `/api/v1/health`), `collector.railway.toml`, and `frontend/railway.toml`. Both backend services read `PORT`.

Before production:

1. Set real values for every credential in `.env.example`.
2. Set `DARKPULSE_ENVIRONMENT=production` and an `https://` `DARKPULSE_FRONTEND_ORIGIN`.
3. Load reviewed blocklists into `safety/policy/prepublish-v1.json`.
4. Enable a live source only with written authorization and a reviewed entry in `config/onion-review.json` for onion seeds (checklist in `docs/onion-review.md`).

## Safety

DarkPulse never buys, messages targets, joins private sources, or logs in to gated markets. Actor links are hypotheses for an investigator to confirm. Viewer accounts do not receive wallets, contacts, PGP fingerprints, or identity hypotheses. A sealed export is not a claim of legal admissibility.

## Development

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux/macOS
pip install -e ".[dev,langid]"  # langid adds fastText; it has no wheel for Python 3.13 on Windows
python -m pytest tests -q
python -m ruff check src tests scripts
python -m mypy src

cd frontend
npm ci
npm run lint
npm test
npm run build
```

`scripts/download_models.py` fetches the fastText language model and the spaCy multilingual model and exits non-zero if either fails. `scripts/train_intent.py` trains an intent model from Gwern data fetched by `scripts/fetch_gwern_data.py`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| Backend exits at startup | Read the last log line: it names the missing token map, password, or TLS setting |
| NLP logs "fasttext not available" | Install the `langid` extra and run `python scripts/download_models.py` |
| Desk shows the Retry screen | The API was unreachable while checking the session; confirm `/api/v1/health` |
| Alerts show "WS refused" | The socket ticket or origin was rejected; sign in again and check `DARKPULSE_FRONTEND_ORIGIN` |
| Telegram auth fails | Set the API id and hash, then run `python -m darkpulse.cli telegram-auth` |
