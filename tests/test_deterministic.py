from __future__ import annotations

from darkpulse.nlp.ner.deterministic import (
    extract_contacts,
    extract_crypto_wallets,
    extract_pgp_fingerprints,
    extract_prices,
    extract_quantities,
)


class TestCryptoWalletExtraction:
    def test_btc_legacy(self):
        text = "Send to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
        wallets = extract_crypto_wallets(text)
        assert len(wallets) >= 1
        assert any(w.chain == "BTC" for w in wallets)

    def test_btc_bech32(self):
        text = "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq"
        wallets = extract_crypto_wallets(text)
        assert len(wallets) >= 1
        assert any(w.chain == "BTC" for w in wallets)

    def test_eth_address(self):
        text = "ETH: 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18"
        wallets = extract_crypto_wallets(text)
        assert len(wallets) >= 1
        assert any(w.chain == "ETH" for w in wallets)

    def test_multiple_wallets(self):
        text = """
        BTC: 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa
        ETH: 0x742d35Cc6634C0532925a3b844Bc9e7595f2bD18
        """
        wallets = extract_crypto_wallets(text)
        assert len(wallets) >= 2

    def test_no_wallets(self):
        text = "No cryptocurrency addresses here."
        wallets = extract_crypto_wallets(text)
        assert len(wallets) == 0


class TestPGPExtraction:
    def test_full_fingerprint(self):
        text = "PGP: 0x1234567890ABCDEF1234567890ABCDEF12345678"
        fps = extract_pgp_fingerprints(text)
        assert len(fps) >= 1

    def test_no_pgp(self):
        text = "No PGP keys here."
        fps = extract_pgp_fingerprints(text)
        assert len(fps) == 0


class TestContactExtraction:
    def test_telegram_handle(self, sample_with_contacts):
        contacts = extract_contacts(sample_with_contacts)
        telegram = [c for c in contacts if c.type.value == "telegram"]
        assert len(telegram) >= 1

    def test_email(self, sample_with_contacts):
        contacts = extract_contacts(sample_with_contacts)
        email = [c for c in contacts if c.type.value == "email"]
        assert len(email) >= 1

    def test_no_contacts(self):
        text = "No contact information here."
        contacts = extract_contacts(text)
        assert len(contacts) == 0


class TestPriceExtraction:
    def test_usd_price(self):
        text = "Price: $50 for 10 pills"
        prices = extract_prices(text)
        assert len(prices) >= 1
        assert prices[0].currency == "USD"
        assert prices[0].amount == 50.0

    def test_btc_price(self):
        text = "0.005 BTC per gram"
        prices = extract_prices(text)
        assert len(prices) >= 1
        assert prices[0].currency == "BTC"

    def test_inr_price(self):
        text = "₹500 per gram"
        prices = extract_prices(text)
        assert len(prices) >= 1
        assert prices[0].currency == "INR"


class TestQuantityExtraction:
    def test_grams(self):
        text = "5 grams of cocaine"
        quantities = extract_quantities(text)
        assert len(quantities) >= 1
        assert quantities[0].unit == "g"

    def test_pills(self):
        text = "10 pills of MDMA"
        quantities = extract_quantities(text)
        assert len(quantities) >= 1
        assert quantities[0].unit == "pills"

    def test_slang_quantities(self):
        text = "Got an eighth and a quarter"
        quantities = extract_quantities(text)
        assert len(quantities) >= 1
