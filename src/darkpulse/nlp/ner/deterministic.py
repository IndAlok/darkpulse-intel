from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from darkpulse.models import Contact, ContactType, CryptoWallet

logger = logging.getLogger(__name__)


_BTC_PATTERNS = [
    re.compile(r"\b[13][a-km-zA-HJ-NP-Z1-9]{25,34}\b"),
    re.compile(r"\bbc1[a-z0-9]{39,59}\b"),
    re.compile(r"\bbc1p[a-z0-9]{58}\b"),
]

_ETH_PATTERN = re.compile(r"\b0x[0-9a-fA-F]{40}\b")

_XMR_PATTERN = re.compile(r"\b[48][0-9AB][1-9A-HJ-NP-Za-km-z]{93}\b")

_LTC_PATTERNS = [
    re.compile(r"\b[LM][a-km-zA-HJ-NP-Z1-9]{26,33}\b"),
    re.compile(r"\bltc1[a-z0-9]{39,59}\b"),
]

_BCH_PATTERN = re.compile(r"\b(?:bitcoincash:)?[qp][a-z0-9]{41}\b")

_XRP_PATTERN = re.compile(r"\br[a-km-zA-HJ-NP-Z1-9]{24,34}\b")

_SOL_PATTERN = re.compile(r"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b")


def _validate_btc_checksum(address: str) -> bool:
    if address.startswith("bc1"):
        return len(address) >= 42
    if len(address) < 26 or len(address) > 35:
        return False
    invalid_chars = set("0OIl")
    return not any(c in invalid_chars for c in address[1:])


def extract_crypto_wallets(text: str) -> list[CryptoWallet]:
    wallets: list[CryptoWallet] = []
    seen: set[str] = set()

    def _add(chain: str, pattern: re.Pattern[str]) -> None:
        for match in pattern.finditer(text):
            addr = match.group().strip()
            if addr not in seen:
                if chain == "BTC" and not _validate_btc_checksum(addr):
                    continue
                seen.add(addr)
                wallets.append(CryptoWallet(chain=chain, address=addr))

    _add("BTC", _BTC_PATTERNS[0])
    _add("BTC", _BTC_PATTERNS[1])
    _add("BTC", _BTC_PATTERNS[2])
    _add("ETH", _ETH_PATTERN)
    _add("XMR", _XMR_PATTERN)
    _add("LTC", _LTC_PATTERNS[0])
    _add("LTC", _LTC_PATTERNS[1])
    _add("BCH", _BCH_PATTERN)
    _add("XRP", _XRP_PATTERN)

    return wallets


_PGP_FINGERPRINT_PATTERN = re.compile(r"(?:0x)?[0-9a-fA-F]{4}(?:[\s:]?[0-9a-fA-F]{4}){9}")

_PGP_SHORT_ID = re.compile(r"\b0x[0-9a-fA-F]{8}(?:[0-9a-fA-F]{8})?\b")


def extract_pgp_fingerprints(text: str) -> list[str]:
    fingerprints: list[str] = []
    seen: set[str] = set()

    for match in _PGP_FINGERPRINT_PATTERN.finditer(text):
        fp = re.sub(r"[\s:]", "", match.group()).upper()
        if fp.startswith("0X"):
            fp = fp[2:]
        if len(fp) == 40 and fp not in seen:
            seen.add(fp)
            fingerprints.append(fp)

    for match in _PGP_SHORT_ID.finditer(text):
        kid = match.group().upper().replace("0X", "")
        if len(kid) >= 8 and kid not in seen:
            seen.add(kid)
            fingerprints.append(kid)

    return fingerprints


_TELEGRAM_PATTERN = re.compile(r"(?:@|t\.me/|telegram\.me/)([a-zA-Z0-9_]{5,32})")

_WICKR_PATTERN = re.compile(
    r"(?:wickr(?:me)?:\s*|wickr\s+(?:me\s+)?(?:id\s*[:=]\s*)?)([a-zA-Z0-9_.-]+)",
    re.I,
)

_SIGNAL_PATTERN = re.compile(
    r"(?:signal:\s*|signal\s+(?:id\s*[:=]\s*)?)([a-zA-Z0-9_.+-]+)",
    re.I,
)

_EMAIL_PATTERN = re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")

_PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?\d{3,4}[\s.-]?\d{3,4}")

_JABBER_PATTERN = re.compile(
    r"(?:jabber|xmpp|jid):\s*([a-zA-Z0-9_.+-]+@[a-zA-Z0-9.-]+)",
    re.I,
)


def _redact_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    if len(digits) >= 10:
        return f"+{digits[:2]}...{digits[-2:]}"
    return "..."


def extract_contacts(text: str) -> list[Contact]:
    contacts: list[Contact] = []
    seen: set[str] = set()

    for match in _TELEGRAM_PATTERN.finditer(text):
        handle = match.group(1).lower()
        key = f"telegram:{handle}"
        if key not in seen:
            seen.add(key)
            contacts.append(
                Contact(
                    type=ContactType.TELEGRAM,
                    value_redacted=f"@{handle[:3]}***",
                )
            )

    for match in _WICKR_PATTERN.finditer(text):
        handle = match.group(1).lower()
        key = f"wickr:{handle}"
        if key not in seen:
            seen.add(key)
            contacts.append(
                Contact(
                    type=ContactType.WICKR,
                    value_redacted=f"{handle[:3]}***",
                )
            )

    for match in _SIGNAL_PATTERN.finditer(text):
        handle = match.group(1).lower()
        key = f"signal:{handle}"
        if key not in seen:
            seen.add(key)
            contacts.append(
                Contact(
                    type=ContactType.SIGNAL,
                    value_redacted=f"{handle[:3]}***",
                )
            )

    for match in _EMAIL_PATTERN.finditer(text):
        email = match.group().lower()
        key = f"email:{email}"
        if key not in seen:
            seen.add(key)
            local, domain = email.split("@", 1)
            contacts.append(
                Contact(
                    type=ContactType.EMAIL,
                    value_redacted=f"{local[:2]}***@{domain}",
                )
            )

    for match in _PHONE_PATTERN.finditer(text):
        phone = match.group()
        digits = re.sub(r"\D", "", phone)
        if len(digits) >= 10:
            key = f"phone:{digits}"
            if key not in seen:
                seen.add(key)
                contacts.append(
                    Contact(
                        type=ContactType.PHONE_REDACTED,
                        value_redacted=_redact_phone(phone),
                    )
                )

    for match in _JABBER_PATTERN.finditer(text):
        jid = match.group(1).lower()
        key = f"jabber:{jid}"
        if key not in seen:
            seen.add(key)
            user, domain = jid.split("@", 1)
            contacts.append(
                Contact(
                    type=ContactType.EMAIL,
                    value_redacted=f"{user[:2]}***@{domain}",
                )
            )

    return contacts


_PRICE_PATTERNS = [
    re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)\s*(?:USD)?", re.I),
    re.compile(r"(?:₹|Rs\.?|INR)\s*(\d+(?:,\d{3})*(?:\.\d{1,2})?)", re.I),
    re.compile(r"(\d+(?:\.\d{1,8})?)\s*(?:BTC|btc|₿)"),
    re.compile(r"(\d+(?:\.\d{1,8})?)\s*(?:ETH|eth)"),
    re.compile(r"(\d+(?:\.\d{1,12})?)\s*(?:XMR|xmr)"),
    re.compile(r"€\s*(\d+(?:\.\d{1,2})?)", re.I),
    re.compile(r"£\s*(\d+(?:\.\d{1,2})?)", re.I),
]

_QUANTITY_PATTERNS = [
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:g|gram|grams|gm|gms)\b", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:kg|kilo|kilos|kilogram|kilograms)\b", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:oz|ounce|ounces)\b", re.I),
    re.compile(r"(\d+(?:\.\d+)?)\s*(?:lb|lbs|pound|pounds)\b", re.I),
    re.compile(r"(\d+)\s*(?:pills?|tabs?|caps?|capsules?|tablets?)\b", re.I),
    re.compile(r"(\d+)\s*(?:bags?|packets?|packs?|bags?)\b", re.I),
    re.compile(r"(\d+)\s*(?:blotters?|hits?|strips?|sheets?)\b", re.I),
    re.compile(r"(\d+)\s*(?:vials?|bottles?|ml)\b", re.I),
    re.compile(r"\b(eighth|quarter|half|zip|key|brick)\b", re.I),
]


@dataclass
class ExtractedPrice:
    amount: float
    currency: str
    raw: str


@dataclass
class ExtractedQuantity:
    amount: float | str
    unit: str
    raw: str


def extract_prices(text: str) -> list[ExtractedPrice]:
    prices: list[ExtractedPrice] = []
    seen: set[str] = set()

    currency_map = {
        0: "USD",
        1: "INR",
        2: "BTC",
        3: "ETH",
        4: "XMR",
        5: "EUR",
        6: "GBP",
    }

    for i, pattern in enumerate(_PRICE_PATTERNS):
        for match in pattern.finditer(text):
            raw = match.group()
            if raw not in seen:
                seen.add(raw)
                try:
                    amount_str = match.group(1).replace(",", "")
                    amount = float(amount_str)
                    prices.append(
                        ExtractedPrice(
                            amount=amount,
                            currency=currency_map.get(i, "UNKNOWN"),
                            raw=raw,
                        )
                    )
                except (ValueError, IndexError):
                    continue

    return prices


def extract_quantities(text: str) -> list[ExtractedQuantity]:
    quantities: list[ExtractedQuantity] = []
    seen: set[str] = set()

    unit_map = {
        0: "g",
        1: "kg",
        2: "oz",
        3: "lb",
        4: "pills",
        5: "bags",
        6: "blotters",
        7: "vials",
        8: "slang",
    }

    for i, pattern in enumerate(_QUANTITY_PATTERNS):
        for match in pattern.finditer(text):
            raw = match.group()
            if raw not in seen:
                seen.add(raw)
                try:
                    amount_str = match.group(1)
                    try:
                        amount: float | str = float(amount_str)
                    except ValueError:
                        amount = amount_str

                    quantities.append(
                        ExtractedQuantity(
                            amount=amount,
                            unit=unit_map.get(i, "unknown"),
                            raw=raw,
                        )
                    )
                except (ValueError, IndexError):
                    continue

    return quantities


def extract_all_deterministic(text: str) -> dict[str, Any]:
    return {
        "crypto_wallets": extract_crypto_wallets(text),
        "pgp_fingerprints": extract_pgp_fingerprints(text),
        "contacts": extract_contacts(text),
        "prices": extract_prices(text),
        "quantities": extract_quantities(text),
    }
