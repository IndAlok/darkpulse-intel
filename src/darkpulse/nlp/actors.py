from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

from darkpulse.models import ActorLink, ActorRelation, Entities

logger = logging.getLogger(__name__)

_USERNAME_SUBS: dict[str, str] = {
    "0": "o",
    "1": "i",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "9": "g",
    "$": "s",
    "!": "i",
}

_STRIP_CHARS = re.compile(r"[._\-@ ]+")


def normalize_username(username: str) -> str:
    if not username:
        return ""

    normalized = username.lower().strip()

    normalized = _STRIP_CHARS.sub("", normalized)

    result = list(normalized)
    for i, char in enumerate(result):
        if char in _USERNAME_SUBS:
            result[i] = _USERNAME_SUBS[char]

    normalized = "".join(result)

    return re.sub(r"[^a-z0-9]", "", normalized)


@dataclass
class ActorProfile:
    aliases: list[str]
    platform: str
    pgp_fingerprints: list[str]
    crypto_wallets: list[str]
    contacts: list[str]


def extract_actor_profile(entities: Entities, platform: str = "") -> ActorProfile:
    aliases = [v.alias for v in entities.vendors if v.alias]
    pgp_fps = entities.pgp_fingerprints or []
    wallets = [w.address for w in entities.crypto_wallets if w.address]
    contacts = [c.value_redacted for c in entities.contacts if c.value_redacted]

    return ActorProfile(
        aliases=aliases,
        platform=platform,
        pgp_fingerprints=pgp_fps,
        crypto_wallets=wallets,
        contacts=contacts,
    )


def detect_username_links(
    current_aliases: list[str],
    known_aliases: dict[str, list[str]],
) -> list[ActorLink]:
    links: list[ActorLink] = []

    for alias in current_aliases:
        normalized = normalize_username(alias)
        if not normalized or len(normalized) < 3:
            continue

        for canonical_id, known_list in known_aliases.items():
            for known_alias in known_list:
                known_normalized = normalize_username(known_alias)
                if not known_normalized:
                    continue

                if normalized == known_normalized:
                    links.append(
                        ActorLink(
                            from_actor=alias,
                            to_actor=canonical_id,
                            relation=ActorRelation.SAME_AS,
                            confidence=0.85,
                        )
                    )
                    break

                if (
                    len(normalized) >= 5
                    and len(known_normalized) >= 5
                    and (
                        normalized.startswith(known_normalized)
                        or known_normalized.startswith(normalized)
                    )
                ):
                    links.append(
                        ActorLink(
                            from_actor=alias,
                            to_actor=canonical_id,
                            relation=ActorRelation.SAME_AS,
                            confidence=0.65,
                        )
                    )
                    break

    return links


def detect_pgp_links(
    current_fps: list[str],
    known_fps: dict[str, list[str]],
) -> list[ActorLink]:
    links: list[ActorLink] = []

    for fp in current_fps:
        fp_upper = fp.upper()
        for canonical_id, known_list in known_fps.items():
            for known_fp in known_list:
                if fp_upper == known_fp.upper():
                    links.append(
                        ActorLink(
                            from_actor=fp,
                            to_actor=canonical_id,
                            relation=ActorRelation.SAME_AS,
                            confidence=0.95,
                        )
                    )
                    break

                if (
                    len(fp_upper) >= 8
                    and len(known_fp) >= 8
                    and fp_upper[-8:] == known_fp.upper()[-8:]
                ):
                    links.append(
                        ActorLink(
                            from_actor=fp,
                            to_actor=canonical_id,
                            relation=ActorRelation.SAME_AS,
                            confidence=0.7,
                        )
                    )
                    break

    return links


def detect_wallet_links(
    current_wallets: list[str],
    known_wallets: dict[str, list[str]],
) -> list[ActorLink]:
    links: list[ActorLink] = []

    for wallet in current_wallets:
        wallet_lower = wallet.lower()
        for canonical_id, known_list in known_wallets.items():
            for known_wallet in known_list:
                if wallet_lower == known_wallet.lower():
                    links.append(
                        ActorLink(
                            from_actor=wallet,
                            to_actor=canonical_id,
                            relation=ActorRelation.USES_WALLET,
                            confidence=0.9,
                        )
                    )
                    break

    return links


def detect_vending_links(
    vendor_alias: str,
    platform: str,
    known_vendors: dict[str, dict[str, Any]],
) -> list[ActorLink]:
    links: list[ActorLink] = []
    normalized = normalize_username(vendor_alias)

    if not normalized:
        return links

    for canonical_id, vendor_data in known_vendors.items():
        known_platforms = vendor_data.get("platforms", [])
        known_aliases = vendor_data.get("aliases", [])

        if platform and platform not in known_platforms:
            for known_alias in known_aliases:
                if normalize_username(known_alias) == normalized:
                    links.append(
                        ActorLink(
                            from_actor=vendor_alias,
                            to_actor=canonical_id,
                            relation=ActorRelation.VENDS_ON,
                            confidence=0.75,
                        )
                    )
                    break

    return links


def detect_all_actor_links(
    entities: Entities,
    source_class: str = "",
    known_actors: dict[str, Any] | None = None,
) -> list[ActorLink]:
    all_links: list[ActorLink] = []

    if not known_actors:
        return all_links

    profile = extract_actor_profile(entities, source_class)

    known_aliases = known_actors.get("aliases", {})
    all_links.extend(detect_username_links(profile.aliases, known_aliases))

    known_fps = known_actors.get("pgp_fingerprints", {})
    all_links.extend(detect_pgp_links(profile.pgp_fingerprints, known_fps))

    known_wallets = known_actors.get("crypto_wallets", {})
    all_links.extend(detect_wallet_links(profile.crypto_wallets, known_wallets))

    known_vendors = known_actors.get("vendors", {})
    for alias in profile.aliases:
        all_links.extend(detect_vending_links(alias, source_class, known_vendors))

    seen: set[tuple[str, str, str]] = set()
    unique_links: list[ActorLink] = []
    for link in all_links:
        key = (link.from_actor, link.to_actor, link.relation.value)
        if key not in seen:
            seen.add(key)
            unique_links.append(link)

    return unique_links
