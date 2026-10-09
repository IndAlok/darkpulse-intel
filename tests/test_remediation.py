from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
from starlette.websockets import WebSocketDisconnect

from darkpulse.api.app import app
from darkpulse.api.deps import get_mongo, get_settings
from darkpulse.api.routes.evidence import generate_seal
from darkpulse.api.security import Principal, mint_session, open_mode_principal
from darkpulse.broker.processor import _term_in_text
from darkpulse.config import Settings, enforce_boot
from darkpulse.ingestion.dedup import InMemoryDedupStore
from darkpulse.ingestion.metrics import IngestionMetrics
from darkpulse.ingestion.pipeline import IngestionPipeline, OutcomeStatus
from darkpulse.ingestion.safety import SafetyPolicy
from darkpulse.ingestion.validation import ContractValidator
from darkpulse.nlp.geo import match_explicit
from darkpulse.nlp.language import fold_leetspeak
from darkpulse.nlp.pipeline import NLPPipeline
from darkpulse.nlp.slang import SlangDictionary

REPO_ROOT = __import__("pathlib").Path(__file__).resolve().parents[1]
CONTRACT_PATH = REPO_ROOT / "contracts/contract1-raw-ingest.schema.json"
SAFETY_POLICY_PATH = REPO_ROOT / "safety/policy/prepublish-v1.json"
TOKEN = "0123456789abcdef0123456789abcdef"


def _auth_settings() -> Settings:
    settings = Settings()
    settings.auth.enabled = True
    settings.auth.local_open_mode = False
    settings.auth.tokens_json = SecretStr(f'{{"{TOKEN}": {{"subject": "a-1", "role": "analyst"}}}}')
    return settings


def test_open_mode_requires_a_local_peer() -> None:
    settings = Settings()
    settings.auth.enabled = False
    settings.auth.local_open_mode = True
    assert open_mode_principal(settings, "127.0.0.1") is not None
    assert open_mode_principal(settings, "203.0.113.5") is None
    settings.auth.local_open_mode = False
    assert open_mode_principal(settings, "127.0.0.1") is None


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"auth.local_open_mode": True, "auth.enabled": False, "service.api_host": "0.0.0.0"},
         "loopback"),
        ({"auth.local_open_mode": True, "auth.enabled": False, "service.api_host": "127.0.0.1",
          "service.environment": "production"}, "not allowed in production"),
        ({"auth.local_open_mode": False, "auth.enabled": True,
          "auth.tokens_json": SecretStr('{"short": {"subject": "a", "role": "viewer"}}')},
         "32 random characters"),
        ({"auth.local_open_mode": False, "auth.enabled": False}, "required unless"),
    ],
)
def test_boot_guards(change: dict[str, object], message: str) -> None:
    settings = Settings()
    settings.neo4j.password = "a-real-password"
    for dotted, value in change.items():
        section, field = dotted.split(".")
        setattr(getattr(settings, section), field, value)
    with pytest.raises(RuntimeError, match=message):
        enforce_boot(settings)


def test_documented_env_names_bind(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARKPULSE_PROCESSOR_POLL_INTERVAL_SECONDS", "3.5")
    monkeypatch.setenv("DARKPULSE_GEO_CITY", "Vadodara")
    monkeypatch.setenv("DARKPULSE_TELEGRAM_API_ID", "")
    settings = Settings(_env_file=None)
    assert settings.processor.poll_interval_seconds == 3.5
    assert settings.geo.city == "Vadodara"
    assert settings.collection.telegram_api_id is None


def test_severity_weights_must_sum_to_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DARKPULSE_SEVERITY_INTENT", "0.9")
    with pytest.raises(ValueError, match="sum to 1.0"):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("c0c@ine", "cocaine"), ("w33d", "weed"), ("10g", "10g"), ("Rs500", "Rs500"),
     ("@surat_dealer", "@surat_dealer"), ("bob@gmail.com", "bob@gmail.com")],
)
def test_leetspeak_folds_words_but_not_quantities(raw: str, expected: str) -> None:
    assert fold_leetspeak(raw)[0] == expected


def test_geo_and_watchlist_matching_use_word_boundaries() -> None:
    assert match_explicit("The palace station mushroom soup was good")[0] is None
    assert match_explicit("meet at Pal tonight")[0] == "pal"
    assert not _term_in_text("ice", "the police arrived")
    assert _term_in_text("md", "selling md near adajan")


def test_unrelated_news_is_dropped() -> None:
    pipeline = NLPPipeline(slang_dictionary=SlangDictionary())
    record = MagicMock(
        ingest_id="00000000-0000-0000-0000-000000000001",
        trace_id="00000000-0000-0000-0000-000000000002",
        source_class="social",
        raw_content="The state cabinet met on Tuesday to discuss a new road budget in Surat.",
        geo_hints=[],
        source_metadata={},
    )
    record.captured_at = __import__("datetime").datetime.now(__import__("datetime").UTC)
    assert pipeline.process(record) is None


@pytest.mark.asyncio
async def test_replayed_publish_is_a_duplicate(source_record) -> None:
    publisher = MagicMock()
    publisher.publish = AsyncMock(return_value=False)
    pipeline = IngestionPipeline(
        safety_policy=SafetyPolicy.from_path(SAFETY_POLICY_PATH),
        dedup_store=InMemoryDedupStore(),
        publisher=publisher,
        validator=ContractValidator(CONTRACT_PATH),
        metrics=IngestionMetrics(),
        collector_id="test",
        collector_version="1.0.0",
    )
    outcome = await pipeline.process(source_record)
    assert outcome.status is OutcomeStatus.DUPLICATE


@pytest.mark.asyncio
async def test_resealing_the_same_bytes_returns_the_existing_seal() -> None:
    db = MagicMock()
    existing = {"_id": "x", "hash_sha256": "h", "sealed_at": 1, "previous_hash": None}
    db.evidence.find_one = AsyncMock(return_value=existing)
    db.evidence.insert_one = AsyncMock()
    seal = await generate_seal(b"same", db, Settings())
    assert seal["hash_sha256"] == "h"
    db.evidence.insert_one.assert_not_called()


def _client(mongo: MagicMock) -> TestClient:
    app.dependency_overrides[get_mongo] = lambda: mongo
    app.dependency_overrides[get_settings] = _auth_settings
    return TestClient(app)


def test_static_token_is_only_valid_at_login_and_logout_revokes() -> None:
    mongo = AsyncMock()
    try:
        with _client(mongo) as client:
            static = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {TOKEN}"})
            assert static.status_code == 401
            session = client.post("/api/v1/auth/login", json={"token": TOKEN}).json()["data"]
            headers = {"Authorization": f"Bearer {session['token']}"}
            assert client.get("/api/v1/auth/me", headers=headers).status_code == 200
            assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
            assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_redis_rate_window_is_shared() -> None:
    from darkpulse.api.rate_limit import _WRITE_LIMIT, _charge_redis

    redis = AsyncMock()
    redis.incr = AsyncMock(side_effect=lambda key: _WRITE_LIMIT + 1)
    redis.ttl = AsyncMock(return_value=30)
    assert await _charge_redis(redis, "analyst-1:/api/v1/export") is False
    redis.expire.assert_not_called()


def test_export_requires_ids() -> None:
    mongo = AsyncMock()
    bearer = mint_session(Principal(subject="a-1", role="analyst"), TOKEN)
    try:
        with _client(mongo) as client:
            response = client.post(
                "/api/v1/export?format=csv", headers={"Authorization": f"Bearer {bearer}"}
            )
        assert response.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_alert_socket_rejects_query_tokens_and_missing_tickets() -> None:
    settings = _auth_settings()
    settings.neo4j.password = "a-real-password"
    with (
        patch("darkpulse.api.app.get_settings", return_value=settings),
        TestClient(app) as client,
    ):
        for path in ("/api/v1/alerts/ws?access_token=x", "/api/v1/alerts/ws"):
            with pytest.raises(WebSocketDisconnect), client.websocket_connect(
                path, headers={"origin": "http://localhost:5173"}
            ) as socket:
                socket.receive_text()


@pytest.mark.asyncio
async def test_discover_prints_candidates_and_stores_nothing(tmp_path, monkeypatch, capsys) -> None:
    from darkpulse import cli
    from darkpulse.ingestion.collectors.discovery import DiscoveryResult, OnionCandidate

    engines = tmp_path / "engines.json"
    engines.write_text(
        '[{"engine_id": "engine-a", "search_url_template": "https://search.example/?q={query}"}]',
        encoding="utf-8",
    )
    result = DiscoveryResult(
        candidates=(
            OnionCandidate(candidate_id="c1", url="http://x.onion/", discovered_by=("engine-a",)),
        ),
        failed_engines=(),
    )
    monkeypatch.setattr(cli.DarkWebSearchAggregator, "search", AsyncMock(return_value=result))
    code = await cli.async_main(["discover", "--engines", str(engines), "--query", "surat"])
    out = capsys.readouterr().out
    assert code == 0
    assert '"candidate_id": "c1"' in out


@pytest.mark.live_datastores
@pytest.mark.asyncio
async def test_unconnected_mongo_health_reports_disconnected() -> None:
    from darkpulse.storage.mongodb import MongoManager

    manager = MongoManager(Settings().mongo)
    assert await manager.health() == {"status": "disconnected"}


def test_expired_token_cannot_log_in() -> None:
    from datetime import UTC, datetime, timedelta

    from darkpulse.api.security import configured_principal

    settings = Settings()
    settings.auth.enabled = True
    settings.auth.local_open_mode = False
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    settings.auth.tokens_json = SecretStr(
        f'{{"{TOKEN}": {{"subject": "a-1", "role": "analyst", "expires_at": "{past}"}}}}'
    )
    with pytest.raises(HTTPException) as excinfo:
        configured_principal(TOKEN, settings)
    assert excinfo.value.status_code == 401


@pytest.mark.asyncio
async def test_dead_letter_retry_resets_exhausted_rows() -> None:
    from darkpulse.api.deps import get_mongo, get_settings

    mongo = AsyncMock()
    mongo.raw_ingest.update_one = AsyncMock(return_value=MagicMock(matched_count=1))
    admin_settings = Settings()
    admin_settings.auth.enabled = True
    admin_settings.auth.local_open_mode = False
    admin_settings.auth.tokens_json = SecretStr(
        f'{{"{TOKEN}": {{"subject": "admin-001", "role": "administrator"}}}}'
    )
    app.dependency_overrides[get_mongo] = lambda: mongo
    app.dependency_overrides[get_settings] = lambda: admin_settings
    try:
        with TestClient(app) as client:
            session = client.post("/api/v1/auth/login", json={"token": TOKEN}).json()["data"]
            headers = {"Authorization": f"Bearer {session['token']}"}
            resp = client.post(
                "/api/v1/operations/dead-letter/ing-1/retry", headers=headers
            )
            assert resp.status_code == 200
            assert resp.json()["data"]["status"] == "pending"
    finally:
        app.dependency_overrides.clear()


def test_alert_audience_filter_hides_high_role_frames() -> None:
    from darkpulse.api.routes.alerts import _visible_alert
    from darkpulse.api.security import Principal

    viewer = Principal(subject="v", role="viewer")
    analyst = Principal(subject="a", role="analyst")
    analyst_frame = {"rule_name": "r", "audience": "analyst", "wallet": "x"}
    assert _visible_alert(analyst_frame, viewer) is None
    visible = _visible_alert(analyst_frame, analyst)
    assert visible is not None
    viewer_frame = {"rule_name": "r", "audience": "viewer", "wallet": "x"}
    redacted = _visible_alert(viewer_frame, viewer)
    assert redacted is not None and "wallet" not in redacted


def test_production_accepts_railway_private_datastores() -> None:
    settings = Settings()
    settings.service.environment = "production"
    settings.service.frontend_origin = "https://desk.example.com"
    settings.service.metrics_port = 0
    settings.auth.enabled = True
    settings.auth.local_open_mode = False
    token = "a" * 32
    settings.auth.tokens_json = SecretStr(
        json.dumps({token: {"subject": "analyst-001", "role": "analyst"}})
    )
    settings.neo4j.password = "a-real-password-ok"
    settings.mongo.uri = "mongodb://mongodb.railway.internal:27017"
    settings.redis.url = "redis://redis.railway.internal:6379/0"
    enforce_boot(settings)


def test_production_rejects_public_plaintext_mongo() -> None:
    settings = Settings()
    settings.service.environment = "production"
    settings.service.frontend_origin = "https://desk.example.com"
    settings.service.metrics_port = 0
    settings.auth.enabled = True
    settings.auth.local_open_mode = False
    token = "b" * 32
    settings.auth.tokens_json = SecretStr(
        json.dumps({token: {"subject": "analyst-001", "role": "analyst"}})
    )
    settings.neo4j.password = "a-real-password-ok"
    settings.mongo.uri = "mongodb://db.example.com:27017"
    settings.redis.url = "rediss://redis.example.com:6380/0"
    with pytest.raises(RuntimeError, match="MongoDB URI must use TLS"):
        enforce_boot(settings)


def test_env_must_be_a_known_value() -> None:
    settings = Settings()
    settings.service.environment = "qa-eu-west"
    settings.auth.local_open_mode = True
    settings.service.api_host = "127.0.0.1"
    with pytest.raises(RuntimeError, match="development, staging, or production"):
        enforce_boot(settings)


def test_production_boot_requires_a_csam_blocklist(tmp_path) -> None:
    from darkpulse.ingestion.safety import SafetyPolicy

    policy = tmp_path / "policy.json"
    policy.write_text(
        '''{
            "policy_version": "prepublish-v1",
            "max_source_bytes": 100,
            "max_content_bytes": 100,
            "allowed_content_types": ["text"],
            "allowed_mime_types": ["text/plain"],
            "blocked_content_sha256": []
        }''',
        encoding="utf-8",
    )
    SafetyPolicy.from_path(policy)  # permissive in development
    with pytest.raises(RuntimeError, match="blocked_content_sha256"):
        SafetyPolicy.from_path(policy, require_blocklist=True)
