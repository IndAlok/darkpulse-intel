from darkpulse.api.search_query import expand_search_terms, extract_intel_id, intel_id_candidates


def test_extract_intel_id_accepts_uuid_and_prefix() -> None:
    intel_id = "6cc6569d-47d6-77a3-d0cf-ccbb6a517327"
    assert extract_intel_id(intel_id) == intel_id
    assert extract_intel_id(f"intel:{intel_id}") == intel_id
    assert extract_intel_id("weed") is None
    assert extract_intel_id("Adajan") is None
    assert intel_id_candidates(f"intel:{intel_id}")[0] == f"intel:{intel_id}"
    assert intel_id in intel_id_candidates(f"intel:{intel_id}")


def test_expand_search_terms_includes_weed_synonyms() -> None:
    terms = {term.casefold() for term in expand_search_terms("weed")}
    assert "weed" in terms
    assert "cannabis" in terms
