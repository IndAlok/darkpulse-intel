from __future__ import annotations

from darkpulse.models import GeoLocation
from darkpulse.nlp.geo import (
    SURAT_NEIGHBORHOODS,
    match_explicit,
    match_geo,
    match_ship_from,
    match_slang,
    resolve_neighborhood_names,
)


class TestSuratNeighborhoods:
    def test_neighborhoods_not_empty(self):
        assert len(SURAT_NEIGHBORHOODS) >= 20

    def test_key_neighborhoods_present(self):
        key_neighborhoods = ["adajan", "varachha", "katargam", "udhna", "piplod", "rander"]
        for n in key_neighborhoods:
            assert n in SURAT_NEIGHBORHOODS, f"{n} missing from gazetteer"

    def test_aliases_exist(self):
        for canonical, data in SURAT_NEIGHBORHOODS.items():
            assert "aliases" in data, f"{canonical} missing aliases"
            assert len(data["aliases"]) > 0, f"{canonical} has no aliases"


class TestExplicitMatching:
    def test_exact_match(self):
        text = "Delivery to Adajan area in Surat"
        neighborhood, confidence, terms = match_explicit(text)
        assert neighborhood == "adajan"
        assert confidence > 0.5

    def test_alias_match(self):
        text = "Meet at Adajan Patia"
        neighborhood, confidence, terms = match_explicit(text)
        assert neighborhood == "adajan"

    def test_no_match(self):
        text = "No location mentioned"
        neighborhood, confidence, terms = match_explicit(text)
        assert neighborhood is None

    def test_multiple_neighborhoods(self):
        text = "Delivery from Adajan to Varachha"
        neighborhood, confidence, terms = match_explicit(text)
        assert neighborhood in ("adajan", "varachha")


class TestSlangMatching:
    def test_surat_special(self):
        city, confidence, terms = match_slang("surat special delivery")
        assert city == "surat"
        assert confidence >= 0.7

    def test_generic_delivery_phrase_is_not_surat(self):
        city, confidence, terms = match_slang("fast delivery available")
        assert city is None

    def test_no_slang(self):
        city, confidence, terms = match_slang("no location here")
        assert city is None


class TestShipFromMatching:
    def test_ship_from_surat(self):
        text = "Ships from: Surat, Gujarat"
        location, confidence, terms = match_ship_from(text)
        assert location is not None
        assert "surat" in location.lower() or confidence > 0

    def test_no_ship_from(self):
        text = "No shipping info"
        location, confidence, terms = match_ship_from(text)
        assert location is None


class TestGeoMatch:
    def test_explicit_match(self, sample_listing: str):
        geo = match_geo(sample_listing)
        assert isinstance(geo, GeoLocation)
        assert geo.city == "Surat" or geo.confidence == 0

    def test_returns_geo_location(self):
        geo = match_geo("Test text")
        assert isinstance(geo, GeoLocation)
        assert hasattr(geo, "neighborhood")
        assert hasattr(geo, "city")
        assert hasattr(geo, "confidence")
        assert hasattr(geo, "basis")


def test_resolve_neighborhood_names_is_case_insensitive() -> None:
    names = {name.casefold() for name in resolve_neighborhood_names("Adajan")}
    assert "adajan" in names
    assert "adajan patia" in names
    assert "ghod dod" in {item.casefold() for item in resolve_neighborhood_names("ghoddod")}
