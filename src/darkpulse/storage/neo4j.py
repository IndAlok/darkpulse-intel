from __future__ import annotations

from typing import Any, LiteralString

import structlog
from neo4j import AsyncDriver, AsyncGraphDatabase

from darkpulse.config import Neo4jSettings
from darkpulse.models import ActorRelation

logger = structlog.get_logger(__name__)

CONSTRAINTS: list[LiteralString] = [
    "CREATE CONSTRAINT vendor_alias IF NOT EXISTS FOR (v:Vendor) REQUIRE v.alias IS UNIQUE",
    ("CREATE CONSTRAINT wallet_address IF NOT EXISTS FOR (w:Wallet) REQUIRE w.address IS UNIQUE"),
    ("CREATE CONSTRAINT product_name IF NOT EXISTS FOR (p:Product) REQUIRE p.name IS UNIQUE"),
    (
        "CREATE CONSTRAINT neighborhood_name IF NOT EXISTS "
        "FOR (n:Neighborhood) REQUIRE n.name IS UNIQUE"
    ),
    "CREATE CONSTRAINT market_name IF NOT EXISTS FOR (m:Market) REQUIRE m.name IS UNIQUE",
    "CREATE CONSTRAINT intel_ref IF NOT EXISTS FOR (i:IntelRef) REQUIRE i.intel_id IS UNIQUE",
]

VALID_RELATIONS: frozenset[str] = frozenset(r.value.upper() for r in ActorRelation)


class Neo4jManager:
    def __init__(self, settings: Neo4jSettings) -> None:
        self._settings = settings
        self._driver: AsyncDriver | None = None

    async def connect(self) -> None:
        logger.info("neo4j.connecting", uri=self._settings.uri)
        self._driver = AsyncGraphDatabase.driver(
            self._settings.uri,
            auth=(self._settings.user, self._settings.password),
            max_connection_pool_size=25,
            connection_timeout=60,
        )
        await self._driver.verify_connectivity()
        logger.info("neo4j.connected")
        await self._ensure_schema()

    async def close(self) -> None:
        if self._driver:
            await self._driver.close()
            logger.info("neo4j.disconnected")

    async def health(self) -> dict[str, str | int]:
        if not self._driver:
            return {"status": "disconnected"}
        try:
            import time

            start = time.monotonic()
            await self._driver.verify_connectivity()
            latency_ms = int((time.monotonic() - start) * 1000)
            return {"status": "healthy", "latency_ms": latency_ms}
        except Exception:
            return {"status": "unhealthy"}

    @property
    def driver(self) -> AsyncDriver:
        if self._driver is None:
            msg = "Neo4j not connected. Call connect() first."
            raise RuntimeError(msg)
        return self._driver

    async def upsert_intel_graph(self, intel: dict[str, Any]) -> None:
        async with self.driver.session(database=self._settings.database) as session:
            await session.execute_write(self._upsert_intel_graph_tx, intel)

    @staticmethod
    async def _upsert_intel_graph_tx(tx: Any, intel: dict[str, Any]) -> None:
        intel_id = intel.get("intel_id", "")
        captured_at = intel.get("captured_at", "")
        entities = intel.get("entities") or {}
        vendors = entities.get("vendors", [])
        vendor_aliases = [v.get("alias", "") for v in vendors if v.get("alias")]

        if intel_id:
            await tx.run(
                """
                MERGE (i:IntelRef {intel_id: $intel_id})
                """,
                intel_id=intel_id,
            )

        for alias in vendor_aliases:
            platform = next((v.get("platform", "") for v in vendors if v.get("alias") == alias), "")
            await tx.run(
                """
                MERGE (v:Vendor {alias: $alias})
                ON CREATE SET v.platform = $platform,
                              v.first_seen = $captured_at,
                              v.last_seen = $captured_at
                ON MATCH SET v.last_seen = CASE
                    WHEN $captured_at > v.last_seen THEN $captured_at
                    ELSE v.last_seen END
                """,
                alias=alias,
                platform=platform,
                captured_at=captured_at,
            )
            if intel_id:
                await tx.run(
                    """
                    MATCH (v:Vendor {alias: $alias})
                    MATCH (i:IntelRef {intel_id: $intel_id})
                    MERGE (v)-[:MENTIONED_IN]->(i)
                    """,
                    alias=alias,
                    intel_id=intel_id,
                )
            if platform:
                await tx.run(
                    """
                    MERGE (m:Market {name: $platform})
                    WITH m
                    MATCH (v:Vendor {alias: $alias})
                    MERGE (v)-[:VENDS_ON]->(m)
                    """,
                    platform=platform,
                    alias=alias,
                )

        products = intel.get("products", [])
        for product in products:
            canonical = product.get("canonical", "")
            if not canonical:
                continue
            await tx.run(
                """
                MERGE (p:Product {name: $name})
                """,
                name=canonical,
            )
            if intel_id:
                await tx.run(
                    """
                    MATCH (i:IntelRef {intel_id: $intel_id})
                    MATCH (p:Product {name: $product})
                    MERGE (i)-[:MENTIONS]->(p)
                    """,
                    intel_id=intel_id,
                    product=canonical,
                )
            for alias in vendor_aliases:
                await tx.run(
                    """
                    MATCH (v:Vendor {alias: $alias})
                    MATCH (p:Product {name: $product})
                    MERGE (v)-[:SELLS]->(p)
                    """,
                    alias=alias,
                    product=canonical,
                )

        wallets = entities.get("crypto_wallets", [])
        for wallet in wallets:
            address = wallet.get("address", "")
            chain = wallet.get("chain", "")
            if not address:
                continue
            await tx.run(
                """
                MERGE (w:Wallet {address: $address})
                ON CREATE SET w.chain = $chain
                """,
                address=address,
                chain=chain,
            )
            for alias in vendor_aliases:
                await tx.run(
                    """
                    MATCH (v:Vendor {alias: $alias})
                    MATCH (w:Wallet {address: $address})
                    MERGE (v)-[:USES_WALLET]->(w)
                    """,
                    alias=alias,
                    address=address,
                )

        geo = intel.get("geo") or {}
        neighborhood = geo.get("neighborhood", "")
        if neighborhood:
            await tx.run(
                """
                MERGE (n:Neighborhood {name: $name})
                ON CREATE SET n.city = $city
                """,
                name=neighborhood,
                city=geo.get("city"),
            )
            if intel_id:
                await tx.run(
                    """
                    MATCH (i:IntelRef {intel_id: $intel_id})
                    MATCH (n:Neighborhood {name: $neighborhood})
                    MERGE (i)-[:LOCATED_IN]->(n)
                    """,
                    intel_id=intel_id,
                    neighborhood=neighborhood,
                )
            for alias in vendor_aliases:
                await tx.run(
                    """
                    MATCH (v:Vendor {alias: $alias})
                    MATCH (n:Neighborhood {name: $neighborhood})
                    MERGE (v)-[:SHIPS_FROM]->(n)
                    """,
                    alias=alias,
                    neighborhood=neighborhood,
                )

        for link in intel.get("actor_links", []):
            from_actor = link.get("from", "")
            to_actor = link.get("to", "")
            relation = str(link.get("relation") or "SAME_AS").upper()
            confidence = link.get("confidence", 0.0)
            if not from_actor or not to_actor:
                continue
            if relation not in VALID_RELATIONS:
                logger.warning("neo4j.invalid_relation", relation=relation, intel_id=intel_id)
                continue
            query = (
                "MERGE (a:Vendor {alias: $from_actor}) "
                "MERGE (b:Vendor {alias: $to_actor}) "
                f"MERGE (a)-[r:{relation}]->(b) "
                "ON CREATE SET r.confidence = $confidence "
                "ON MATCH SET r.confidence = CASE "
                "WHEN $confidence > r.confidence THEN $confidence "
                "ELSE r.confidence END "
            )
            await tx.run(
                query,
                from_actor=from_actor,
                to_actor=to_actor,
                confidence=confidence,
            )

    _LABEL_KEY: dict[str, str] = {
        "Vendor": "alias",
        "Wallet": "address",
        "Product": "name",
        "Neighborhood": "name",
        "Market": "name",
        "IntelRef": "intel_id",
    }
    _ID_PREFIX: dict[str, str] = {
        "Vendor": "vendor",
        "Wallet": "wallet",
        "Product": "product",
        "Neighborhood": "neighborhood",
        "Market": "market",
        "IntelRef": "intel",
    }
    _SAFE_PROPS = (
        "alias",
        "name",
        "address",
        "platform",
        "chain",
        "city",
        "intel_id",
        "first_seen",
        "last_seen",
    )

    def _stable_id(self, label: str, props: dict[str, Any]) -> str:
        key = self._LABEL_KEY.get(label, "name")
        value = str(props.get(key) or props.get("alias") or props.get("name") or "")
        prefix = self._ID_PREFIX.get(label, label.lower())
        return f"{prefix}:{value}" if value else prefix

    def _resolve_center(self, center: str, node_type: str) -> tuple[str, str]:
        raw = center.strip()
        for label, prefix in self._ID_PREFIX.items():
            token = f"{prefix}:"
            if raw.startswith(token):
                return label, raw[len(token) :]
        label = node_type if node_type in self._LABEL_KEY else "Vendor"
        return label, raw

    def _public_props(self, props: dict[str, Any]) -> dict[str, Any]:
        return {key: props[key] for key in self._SAFE_PROPS if props.get(key) not in (None, "")}

    async def get_subgraph(
        self,
        center: str | None = None,
        depth: int = 2,
        node_type: str = "Vendor",
        max_nodes: int = 200,
    ) -> dict[str, Any]:
        empty = {
            "nodes": [],
            "edges": [],
            "truncated": False,
            "limits": {"max_nodes": max_nodes},
        }
        if self._driver is None:
            return empty
        async with self.driver.session(database=self._settings.database) as session:
            safe_depth = max(1, min(int(depth), 4))
            if center:
                record = None
                attempts = [self._resolve_center(center, node_type)]
                prefixed = any(
                    center.strip().startswith(f"{prefix}:") for prefix in self._ID_PREFIX.values()
                )
                if not prefixed:
                    for other in self._LABEL_KEY:
                        if other != attempts[0][0]:
                            attempts.append((other, center.strip()))
                for label, key in attempts:
                    prop = self._LABEL_KEY[label]
                    result = await session.run(
                        f"""
                        MATCH (start:{label} {{{prop}: $center}})
                        MATCH path = (start)-[*0..{safe_depth}]-(connected)
                        RETURN collect(DISTINCT connected) AS node_list,
                               collect(DISTINCT relationships(path)) AS edge_lists
                        """,
                        center=key,
                    )
                    candidate = await result.single()
                    if candidate and candidate["node_list"]:
                        record = candidate
                        break
                if record is None:
                    return empty
            else:
                result = await session.run(
                    """
                    MATCH (n)
                    OPTIONAL MATCH (n)-[degree_rel]-()
                    WITH n, count(degree_rel) AS degree
                    ORDER BY degree DESC
                    LIMIT $max_nodes
                    OPTIONAL MATCH (n)-[r]-(connected)
                    RETURN collect(DISTINCT n) + collect(DISTINCT connected) AS node_list,
                           collect(DISTINCT r) AS edge_list
                    """,
                    max_nodes=max_nodes,
                )
                record = await result.single()
                if not record:
                    return empty

            raw_nodes = [node for node in (record["node_list"] or []) if node is not None]
            serialized: list[dict[str, Any]] = []
            for node in raw_nodes:
                labels = list(node.labels)
                label = labels[0] if labels else "Vendor"
                props = dict(node)
                display = (
                    props.get("alias")
                    or props.get("name")
                    or props.get("address")
                    or props.get("intel_id")
                    or ""
                )
                serialized.append(
                    {
                        "id": self._stable_id(label, props),
                        "label": str(display),
                        "type": label,
                        "properties": self._public_props(props),
                    }
                )
            serialized = sorted(
                serialized, key=lambda item: (item["type"], item["label"], item["id"])
            )
            truncated = len(serialized) > max_nodes
            serialized = serialized[:max_nodes]
            keep = {node["id"] for node in serialized}

            raw_rels: list[Any] = []
            try:
                edge_lists = record["edge_lists"]
            except (KeyError, TypeError):
                edge_lists = None
            if edge_lists is not None:
                for group in edge_lists or []:
                    if not group:
                        continue
                    raw_rels.extend(group)
            else:
                raw_rels.extend(record["edge_list"] or [])

            edges: list[dict[str, Any]] = []
            seen_edges: set[tuple[str, str, str]] = set()
            for rel in raw_rels:
                if rel is None:
                    continue
                start_labels = list(rel.start_node.labels)
                end_labels = list(rel.end_node.labels)
                start_label = start_labels[0] if start_labels else "Vendor"
                end_label = end_labels[0] if end_labels else "Vendor"
                source = self._stable_id(start_label, dict(rel.start_node))
                target = self._stable_id(end_label, dict(rel.end_node))
                if source not in keep or target not in keep:
                    continue
                relation = rel.type
                edge_key = (source, target, relation)
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                try:
                    confidence = float(rel.get("confidence") or 0.0)
                except (TypeError, ValueError):
                    confidence = 0.0
                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "relation": relation,
                        "confidence": confidence,
                    }
                )
            return {
                "nodes": serialized,
                "edges": edges,
                "truncated": truncated,
                "limits": {"max_nodes": max_nodes},
            }

    async def _ensure_schema(self) -> None:
        async with self.driver.session(database=self._settings.database) as session:
            for stmt in CONSTRAINTS:
                try:
                    await session.run(stmt)
                except Exception as exc:
                    logger.debug("neo4j.constraint_skip", statement=stmt, error=str(exc))

        logger.info("neo4j.schema_ensured")
