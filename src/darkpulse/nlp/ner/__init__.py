from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from darkpulse.models import (
    Contact,
    CryptoWallet,
    Entities,
    VendorEntity,
)

logger = logging.getLogger(__name__)

_spacy_model: Any = None


def _load_spacy_model() -> Any:
    global _spacy_model
    if _spacy_model is not None:
        return _spacy_model

    try:
        import spacy

        try:
            _spacy_model = spacy.load("xx_ent_wiki_sm")
        except OSError:
            logger.warning("spaCy xx_ent_wiki_sm not found, using blank model")
            _spacy_model = spacy.blank("xx")

        if "entity_ruler" not in _spacy_model.pipe_names:
            if "ner" in _spacy_model.pipe_names:
                ruler = _spacy_model.add_pipe("entity_ruler", before="ner")
            else:
                ruler = _spacy_model.add_pipe("entity_ruler")
        else:
            ruler = _spacy_model.get_pipe("entity_ruler")

        patterns = [
            {
                "label": "PRODUCT",
                "pattern": [
                    {
                        "LOWER": {
                            "IN": [
                                "mdma",
                                "ecstasy",
                                "molly",
                                "cocaine",
                                "heroin",
                                "meth",
                                "lsd",
                                "acid",
                                "weed",
                                "cannabis",
                                "hash",
                                "ketamine",
                                "fentanyl",
                                "mephedrone",
                                "amphetamine",
                                "opium",
                            ]
                        }
                    }
                ],
            },
            {"label": "PRODUCT", "pattern": [{"LOWER": "crystal"}, {"LOWER": "meth"}]},
            {"label": "PRODUCT", "pattern": [{"LOWER": "brown"}, {"LOWER": "sugar"}]},
            {"label": "PRODUCT", "pattern": [{"LOWER": "meow"}, {"LOWER": "meow"}]},
            {"label": "PRODUCT", "pattern": [{"LOWER": "bath"}, {"LOWER": "salts"}]},
            {"label": "PRODUCT", "pattern": [{"LOWER": "synthetic"}, {"LOWER": "cannabinoid"}]},
            {
                "label": "VENDOR",
                "pattern": [
                    {"LOWER": {"IN": ["vendor", "seller", "dealer", "plug"]}},
                    {"IS_ALPHA": True, "LENGTH": {"MIN": 3}},
                ],
            },
            {
                "label": "QUANTITY",
                "pattern": [
                    {"LIKE_NUM": True},
                    {
                        "LOWER": {
                            "IN": ["g", "gram", "grams", "kg", "oz", "pill", "pills", "tab", "tabs"]
                        }
                    },
                ],
            },
        ]
        ruler.add_patterns(patterns)
        logger.info("Loaded spaCy model with custom patterns")

    except ImportError:
        logger.warning("spaCy not available — NER will use deterministic only")
        _spacy_model = None

    return _spacy_model


@dataclass
class ExtractedEntity:
    text: str
    label: str
    start: int
    end: int
    confidence: float
    source: str
    canonical: str | None = None


def extract_entities_spacy(text: str) -> list[ExtractedEntity]:
    model = _load_spacy_model()
    if model is None:
        return []

    entities: list[ExtractedEntity] = []
    doc = model(text)

    for ent in doc.ents:
        entities.append(
            ExtractedEntity(
                text=ent.text,
                label=ent.label_,
                start=ent.start_char,
                end=ent.end_char,
                confidence=0.8,
                source="spacy",
            )
        )

    return entities


def extract_product_mentions(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []

    product_patterns = [
        (r"\b(?:MDMA|ecstasy|molly)\b", "MDMA"),
        (r"\bcocaine\b", "cocaine"),
        (r"\b(?:heroin|chitta)\b", "heroin"),
        (r"\bmeth(?:amphetamine)?\b", "methamphetamine"),
        (r"\b(?:LSD|blotter)\b", "LSD"),
        (r"\b(?:weed|cannabis|marijuana|ganja|kush)\b", "cannabis"),
        (r"\b(?:hash(?:ish)?|charas)\b", "hashish"),
        (r"\b(?:ketamine|special\s*K)\b", "ketamine"),
        (r"\b(?:fentanyl|fent)\b", "fentanyl"),
        (r"\b(?:mephedrone|meow\s*meow|MDPV)\b", "mephedrone"),
        (r"\bamphetamine\b", "amphetamine"),
        (r"\b(?:opium|afim)\b", "opium"),
        (r"\boxycodone\b", "oxycodone"),
        (r"\b(?:xanax|benzo)\b", "xanax"),
        (r"\b(?:GHB|liquid\s*ecstasy)\b", "GHB"),
        (r"\b(?:PCP|angel\s*dust)\b", "PCP"),
        (r"\b(?:spice|K2|synthetic\s*cannabinoid)\b", "synthetic_cannabinoid"),
        (r"\b(?:psilocybin|mushroom|shroom)\b", "psilocybin"),
        (r"\b(?:sizzurp|codeine)\b", "codeine"),
    ]

    for pattern_str, _ in product_patterns:
        pattern = re.compile(pattern_str, re.I)
        for match in pattern.finditer(text):
            entities.append(
                ExtractedEntity(
                    text=match.group(),
                    label="PRODUCT",
                    start=match.start(),
                    end=match.end(),
                    confidence=0.9,
                    source="pattern",
                )
            )

    return entities


def extract_vendor_mentions(text: str) -> list[ExtractedEntity]:
    entities: list[ExtractedEntity] = []

    vendor_patterns = [
        re.compile(r"(?:vendor|seller|dealer|plug|from)\s*[:=@]\s*([A-Za-z0-9_]{3,32})", re.I),
        re.compile(r"(?:by|bought\s+from|ordered\s+from)\s+([A-Za-z0-9_]{3,32})", re.I),
    ]

    for pattern in vendor_patterns:
        for match in pattern.finditer(text):
            vendor_name = match.group(1)
            if vendor_name.lower() not in ("the", "and", "for", "from", "this", "that"):
                entities.append(
                    ExtractedEntity(
                        text=vendor_name,
                        label="VENDOR",
                        start=match.start(1),
                        end=match.end(1),
                        confidence=0.7,
                        source="pattern",
                    )
                )

    return entities


def merge_entities(
    *entity_lists: list[ExtractedEntity],
) -> list[ExtractedEntity]:
    priority = {"deterministic": 0, "pattern": 1, "spacy": 2, "muril": 3}

    all_entities: list[ExtractedEntity] = []
    for entities in entity_lists:
        all_entities.extend(entities)

    all_entities.sort(key=lambda e: (priority.get(e.source, 99), -e.confidence))

    merged: list[ExtractedEntity] = []
    occupied: set[int] = set()

    for entity in all_entities:
        span = set(range(entity.start, entity.end))
        if not span & occupied:
            merged.append(entity)
            occupied |= span

    merged.sort(key=lambda e: e.start)
    return merged


def entities_to_model(
    extracted: list[ExtractedEntity],
    deterministic_wallets: list[CryptoWallet] | None = None,
    deterministic_contacts: list[Contact] | None = None,
    deterministic_pgp: list[str] | None = None,
) -> Entities:
    vendors: list[VendorEntity] = []
    seen_vendors: set[str] = set()

    for entity in extracted:
        if entity.label == "VENDOR":
            name = entity.text.strip()
            if name and name.lower() not in seen_vendors:
                seen_vendors.add(name.lower())
                vendors.append(VendorEntity(alias=name, platform=""))

    return Entities(
        vendors=vendors,
        buyers=[],
        crypto_wallets=deterministic_wallets or [],
        contacts=deterministic_contacts or [],
        pgp_fingerprints=deterministic_pgp or [],
    )


def extract_all_entities(
    text: str,
    deterministic_results: dict[str, Any] | None = None,
) -> tuple[Entities, list[ExtractedEntity]]:
    if deterministic_results is None:
        deterministic_results = {}

    product_entities = extract_product_mentions(text)
    vendor_entities = extract_vendor_mentions(text)

    spacy_entities = extract_entities_spacy(text)

    all_extracted = merge_entities(
        product_entities,
        vendor_entities,
        spacy_entities,
    )

    entities = entities_to_model(
        all_extracted,
        deterministic_wallets=deterministic_results.get("crypto_wallets"),
        deterministic_contacts=deterministic_results.get("contacts"),
        deterministic_pgp=deterministic_results.get("pgp_fingerprints"),
    )

    return entities, all_extracted
