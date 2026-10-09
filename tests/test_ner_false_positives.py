"""False-positive guards: emails, handles, timestamps, ids must not extract as wallets."""

from darkpulse.nlp.ner.deterministic import extract_crypto_wallets

CASES = [
    "email me at happyuser1985@gmail.com now",
    "ping @deepweb_trader_99 on telegram",
    "posted at 12:34:56 UTC on 2026-10-08T10:20:30Z",
    "order 123456789012345 shipped",
    "tracking number ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 sent",
    "verylongproductidentifierAaaa1111222233334444 here",
    "id 4f1e7a5c9b3d2f8a6e0c5b7a9d1f3e2c4b6a8d0f2e4c6a8b0d2f4e6c8a0b1d3f5e",
    "MDMA pills available contact xyz12345678901234567890123456789012",
]


def test_no_false_positive_wallets() -> None:
    for text in CASES:
        assert extract_crypto_wallets(text) == [], f"false positive on: {text}"


def test_solana_real_address_extracts() -> None:
    # base58, 43 chars, starts with a digit (excluded from BTC/XRP patterns)
    addr = "7VfCXTUg4i7oBw8Yf6Lm2pQyKd9NzR5xHb3WqE1jPnTf"
    wallets = extract_crypto_wallets(f"pay to {addr} now")
    assert any(w.chain == "SOL" and w.address == addr for w in wallets)
