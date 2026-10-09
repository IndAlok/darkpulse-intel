from typing import cast

from fastapi import APIRouter, HTTPException, Query, Request
from neo4j.exceptions import DriverError, Neo4jError

from darkpulse.api.audit import audit_event
from darkpulse.api.deps import MongoDep, Neo4jDep
from darkpulse.api.graph_enrich import hydrate_graph
from darkpulse.api.security import ViewerDep
from darkpulse.models import GraphData, GraphEdge, GraphNode

router = APIRouter(prefix="/graph", tags=["Graph"])
_VIEWER_HIDDEN = frozenset({"Wallet", "ActorHypothesis"})


@router.get("", response_model=GraphData)
async def get_graph(
    request: Request,
    neo4j: Neo4jDep,
    mongo: MongoDep,
    principal: ViewerDep,
    center: str | None = None,
    depth: int = Query(default=2, ge=1, le=4),
    node_type: str = Query(
        default="Vendor", pattern="^(Vendor|Wallet|Product|Neighborhood|Market|IntelRef)$"
    ),
    max_nodes: int = Query(default=200, ge=1, le=500),
) -> GraphData:
    try:
        graph_data = await neo4j.get_subgraph(
            center=center, depth=depth, node_type=node_type, max_nodes=max_nodes
        )
    except (RuntimeError, Neo4jError, DriverError) as exc:
        raise HTTPException(status_code=503, detail="Graph store is unavailable") from exc
    nodes, edges = await hydrate_graph(mongo, graph_data["nodes"], graph_data["edges"])
    if principal.role == "viewer":
        hidden = {node["id"] for node in nodes if node.get("type") in _VIEWER_HIDDEN}
        nodes = [node for node in nodes if node["id"] not in hidden]
        edges = [
            edge for edge in edges if edge.get("source") not in hidden
            and edge.get("target") not in hidden
        ]
    await audit_event(
        mongo,
        request,
        principal,
        "graph.read",
        target_type="graph",
        metadata={"node_count": len(nodes), "truncated": graph_data["truncated"]},
    )
    return GraphData(
        nodes=cast(list[GraphNode], nodes),
        edges=cast(list[GraphEdge], edges),
        truncated=cast(bool, graph_data.get("truncated", False)),
        limits=cast(dict[str, int], graph_data.get("limits", {})),
    )
