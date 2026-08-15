from __future__ import annotations

from typing import Any

from darkpulse.api.search_query import extract_intel_id, intel_id_candidates


def _intel_ref_id(node: dict[str, Any]) -> str:
    props = node.get("properties") or {}
    raw = str(props.get("intel_id") or node.get("id") or node.get("label") or "").strip()
    extracted = extract_intel_id(raw)
    if extracted:
        return extracted
    if raw.lower().startswith("intel:"):
        return raw.split(":", 1)[1].strip()
    return raw


def _headline(doc: dict[str, Any]) -> str:
    products = [
        str(item.get("canonical") or item.get("raw_term") or "")
        for item in doc.get("products") or []
        if isinstance(item, dict)
    ]
    products = [item for item in products if item]
    intent = str((doc.get("intent") or {}).get("label") or "").strip()
    place = str((doc.get("geo") or {}).get("neighborhood") or "").strip()
    if products and place:
        return f"{products[0]} · {place}"
    if products:
        return products[0]
    if intent and place:
        return f"{intent} · {place}"
    return intent or str(doc.get("intel_id") or "Intelligence")


def _node_from_doc(doc: dict[str, Any]) -> dict[str, Any]:
    intel_id = str(doc.get("intel_id") or "")
    return {
        "id": f"intel:{intel_id}",
        "label": _headline(doc),
        "type": "IntelRef",
        "properties": {
            "intel_id": intel_id,
            "available": True,
            "severity_band": (doc.get("severity") or {}).get("band") or "",
            "neighborhood": (doc.get("geo") or {}).get("neighborhood") or "",
            "intent": (doc.get("intent") or {}).get("label") or "",
        },
    }


def _query_values(raw_ids: list[str]) -> list[Any]:
    values: list[Any] = []
    seen: set[str] = set()
    for raw in raw_ids:
        for candidate in intel_id_candidates(raw):
            key = str(candidate)
            if key and key not in seen:
                seen.add(key)
                values.append(candidate)
    return values


async def _load_intel_docs(mongo: Any, raw_ids: list[str]) -> dict[str, dict[str, Any]]:
    docs_by_id: dict[str, dict[str, Any]] = {}
    values = _query_values(raw_ids)
    if not values:
        return docs_by_id
    try:
        cursor = mongo.intel.find({"intel_id": {"$in": values}})
        fetched = cursor.to_list(length=max(len(values), 1) + 20)
        docs = await fetched if hasattr(fetched, "__await__") else fetched
    except Exception:
        docs = []
    if isinstance(docs, list):
        for doc in docs:
            if isinstance(doc, dict) and doc.get("intel_id"):
                key = str(doc["intel_id"])
                docs_by_id[key] = doc
                docs_by_id[key.casefold()] = doc
    if len(docs_by_id) >= len({item for item in raw_ids if item}):
        return docs_by_id
    from darkpulse.api.routes.intel import fetch_intel_doc

    for raw in raw_ids:
        already = any(
            docs_by_id.get(candidate) or docs_by_id.get(candidate.casefold())
            for candidate in intel_id_candidates(raw)
        )
        if already:
            continue
        try:
            doc = await fetch_intel_doc(mongo, raw)
        except Exception:
            continue
        if isinstance(doc, dict) and doc.get("intel_id"):
            key = str(doc["intel_id"])
            docs_by_id[key] = doc
            docs_by_id[key.casefold()] = doc
    return docs_by_id


def _lookup(docs_by_id: dict[str, dict[str, Any]], raw: str) -> dict[str, Any] | None:
    for candidate in intel_id_candidates(raw):
        doc = docs_by_id.get(candidate) or docs_by_id.get(candidate.casefold())
        if doc:
            return doc
    return None


async def enrich_graph_nodes(mongo: Any, nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_ids = [_intel_ref_id(node) for node in nodes if node.get("type") == "IntelRef"]
    docs_by_id = await _load_intel_docs(mongo, raw_ids) if raw_ids else {}
    enriched: list[dict[str, Any]] = []
    for node in nodes:
        if node.get("type") != "IntelRef":
            enriched.append(node)
            continue
        props = dict(node.get("properties") or {})
        raw = _intel_ref_id(node)
        doc = _lookup(docs_by_id, raw)
        if doc:
            props.update(_node_from_doc(doc)["properties"])
            enriched.append(
                {
                    **node,
                    "id": f"intel:{doc['intel_id']}",
                    "label": _headline(doc),
                    "properties": props,
                }
            )
            continue
        props["intel_id"] = raw
        if docs_by_id or raw_ids:
            props["available"] = False
        enriched.append({**node, "properties": props})
    return enriched


async def hydrate_graph(
    mongo: Any,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    enriched = await enrich_graph_nodes(mongo, nodes)
    live = [
        node
        for node in enriched
        if node.get("type") == "IntelRef"
        and (node.get("properties") or {}).get("available") is True
    ]
    if live or not any(node.get("type") == "IntelRef" for node in enriched):
        return enriched, edges
    extra_nodes, extra_edges = await _recent_intel_graph(mongo, existing=enriched)
    if not extra_nodes:
        return enriched, edges
    kept = [node for node in enriched if node.get("type") != "IntelRef"] + extra_nodes
    keep = {node["id"] for node in kept}
    merged_edges = [
        edge
        for edge in edges
        if edge.get("source") in keep and edge.get("target") in keep
    ]
    merged_edges.extend(extra_edges)
    return kept, merged_edges


async def _recent_intel_graph(
    mongo: Any, *, existing: list[dict[str, Any]], limit: int = 40
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        cursor = mongo.intel.find({}).sort("captured_at", -1).limit(limit)
        fetched = cursor.to_list(length=limit)
        docs = await fetched if hasattr(fetched, "__await__") else fetched
    except Exception:
        return [], []
    if not isinstance(docs, list):
        return [], []
    existing_ids = {node["id"] for node in existing}
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    for doc in docs:
        if not isinstance(doc, dict) or not doc.get("intel_id"):
            continue
        node = _node_from_doc(doc)
        if node["id"] in existing_ids:
            continue
        nodes.append(node)
        existing_ids.add(node["id"])
        neighborhood = str((doc.get("geo") or {}).get("neighborhood") or "").strip()
        if neighborhood:
            target = f"neighborhood:{neighborhood}"
            if target in existing_ids:
                edges.append(
                    {
                        "source": node["id"],
                        "target": target,
                        "relation": "LOCATED_IN",
                        "confidence": 0.0,
                    }
                )
        for product in doc.get("products") or []:
            name = ""
            if isinstance(product, dict):
                name = str(product.get("canonical") or "")
            if name and f"product:{name}" in existing_ids:
                edges.append(
                    {
                        "source": node["id"],
                        "target": f"product:{name}",
                        "relation": "MENTIONS",
                        "confidence": 0.0,
                    }
                )
    return nodes, edges
