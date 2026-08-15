from __future__ import annotations

from darkpulse.models import ActorRelation, Entities, VendorEntity
from darkpulse.nlp.actors import (
    detect_all_actor_links,
    detect_username_links,
    detect_wallet_links,
    normalize_username,
)


class TestUsernameNormalization:
    def test_lowercase(self):
        assert normalize_username("TestUser") == "testuser"

    def test_strip_separators(self):
        assert normalize_username("test_user") == "testuser"
        assert normalize_username("test-user") == "testuser"
        assert normalize_username("test.user") == "testuser"

    def test_leetspeak(self):
        assert normalize_username("t3st") == "test"

    def test_empty(self):
        assert normalize_username("") == ""
        assert normalize_username(None) == ""

    def test_short_username(self):
        result = normalize_username("ab")
        assert isinstance(result, str)


class TestUsernameLinkDetection:
    def test_exact_normalized_match(self):
        known = {"actor1": ["TestUser"]}
        links = detect_username_links(["test_user"], known)
        assert len(links) >= 1
        assert links[0].relation == ActorRelation.SAME_AS

    def test_no_match(self):
        known = {"actor1": ["alice"]}
        links = detect_username_links(["bob"], known)
        assert len(links) == 0

    def test_prefix_match(self):
        known = {"actor1": ["testuser123"]}
        links = detect_username_links(["testuser"], known)
        assert len(links) == 1


class TestWalletLinkDetection:
    def test_same_wallet(self):
        known = {"actor1": ["0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"]}
        links = detect_wallet_links(
            ["0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"],
            known,
        )
        assert len(links) >= 1
        assert links[0].relation == ActorRelation.USES_WALLET

    def test_different_wallet(self):
        known = {"actor1": ["0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"]}
        links = detect_wallet_links(
            ["0x1234567890abcdef1234567890abcdef12345678"],
            known,
        )
        assert len(links) == 0


class TestDetectAllActorLinks:
    def test_empty_entities(self):
        entities = Entities(
            vendors=[],
            buyers=[],
            crypto_wallets=[],
            contacts=[],
            pgp_fingerprints=[],
        )
        links = detect_all_actor_links(entities)
        assert len(links) == 0

    def test_with_known_actors(self):
        entities = Entities(
            vendors=[VendorEntity(alias="testvendor", platform="telegram")],
            buyers=[],
            crypto_wallets=[],
            contacts=[],
            pgp_fingerprints=[],
        )
        known = {
            "aliases": {"actor1": ["testvendor"]},
            "pgp_fingerprints": {},
            "crypto_wallets": {},
            "vendors": {},
        }
        links = detect_all_actor_links(entities, known_actors=known)
        assert len(links) == 1
        assert links[0].relation == ActorRelation.SAME_AS
