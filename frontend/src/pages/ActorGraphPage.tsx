import { useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import { Link, useSearchParams } from "react-router-dom";
import IntelDetailDrawer from "../components/IntelDetailDrawer";
import { DataState, EmptyState, FilterChip, PageHeader } from "../components/Ui";
import { graphApi } from "../lib/api";
import { formatObject } from "../lib/formatters";
import { intelIdFromGraphNode } from "../lib/intel";
import { useApi } from "../hooks";
import type { GraphNode } from "../types/api";

const COLORS: Record<string, string> = {
  Vendor: "#2ee6c7",
  Product: "#9ec5ff",
  Neighborhood: "#f5c16c",
  Wallet: "#c4b5fd",
  Market: "#f87171",
  IntelRef: "#e7eef4",
};

const WIDTH = 1400;
const HEIGHT = 820;

export default function ActorGraphPage() {
  const [params, setParams] = useSearchParams();
  const center = params.get("center") || "";
  const typeFilter = params.get("type") || "";
  const graph = useApi(() => graphApi.get(center || undefined, 2, 160), center);
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [hovered, setHovered] = useState<string | null>(null);
  const [view, setView] = useState({ x: 0, y: 0, k: 1 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const rawNodes = graph.data?.nodes;
  const rawEdges = graph.data?.edges;
  const nodes = useMemo(() => {
    const source = rawNodes ?? [];
    return typeFilter ? source.filter((node) => node.type === typeFilter) : source;
  }, [rawNodes, typeFilter]);
  const keep = useMemo(() => new Set(nodes.map((node) => node.id)), [nodes]);
  const edges = useMemo(
    () => (rawEdges ?? []).filter((edge) => keep.has(edge.source) && keep.has(edge.target)),
    [rawEdges, keep],
  );
  const layout = useMemo(() => layoutForce(nodes, edges), [nodes, edges]);
  const types = useMemo(() => [...new Set((rawNodes ?? []).map((node) => node.type))], [rawNodes]);

  useEffect(() => {
    if (selected && !nodes.some((node) => node.id === selected.id)) setSelected(null);
  }, [nodes, selected]);

  const setCenter = (value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set("center", value);
    else next.delete("center");
    setParams(next);
  };

  const onWheel = (event: WheelEvent<SVGSVGElement>) => {
    event.preventDefault();
    const rect = event.currentTarget.getBoundingClientRect();
    const mx = ((event.clientX - rect.left) / rect.width) * (WIDTH / view.k) + view.x;
    const my = ((event.clientY - rect.top) / rect.height) * (HEIGHT / view.k) + view.y;
    const nextK = Math.min(3.2, Math.max(0.45, view.k * (event.deltaY < 0 ? 1.12 : 0.88)));
    setView({
      k: nextK,
      x: mx - ((event.clientX - rect.left) / rect.width) * (WIDTH / nextK),
      y: my - ((event.clientY - rect.top) / rect.height) * (HEIGHT / nextK),
    });
  };

  const onPointerDown = (event: PointerEvent<SVGSVGElement>) => {
    if ((event.target as Element).closest("[data-node]")) return;
    drag.current = { x: view.x, y: view.y, px: event.clientX, py: event.clientY };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMoveSimple = (event: PointerEvent<SVGSVGElement>) => {
    if (!drag.current) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const dx = ((event.clientX - drag.current.px) / rect.width) * (WIDTH / view.k);
    const dy = ((event.clientY - drag.current.py) / rect.height) * (HEIGHT / view.k);
    setView({ x: drag.current.x - dx, y: drag.current.y - dy, k: view.k });
  };

  return (
    <div>
      <PageHeader
        eyebrow="INVESTIGATE"
        title="Actor graph"
        description="Pan, zoom, and filter a spaced force layout. Drill-down uses vendor, intel, product, and neighborhood keys."
      />
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          className="min-w-64 flex-1 rounded border border-border bg-surface px-3 py-2 text-sm"
          placeholder="center e.g. vendor:alias or intel:id"
          value={center}
          onChange={(event) => setCenter(event.target.value)}
        />
        <button
          className="rounded border border-border px-3 py-2 text-xs text-muted"
          onClick={() => setView({ x: 0, y: 0, k: 1 })}
        >
          Reset view
        </button>
      </div>
      <div className="mb-3 flex flex-wrap gap-2">
        <FilterChip
          active={!typeFilter}
          onClick={() => {
            const next = new URLSearchParams(params);
            next.delete("type");
            setParams(next);
          }}
        >
          All types
        </FilterChip>
        {types.map((type) => (
          <FilterChip
            key={type}
            active={typeFilter === type}
            onClick={() => {
              const next = new URLSearchParams(params);
              if (typeFilter === type) next.delete("type");
              else next.set("type", type);
              setParams(next);
            }}
          >
            <span className="mr-1 inline-block h-2 w-2 rounded-full" style={{ background: COLORS[type] }} />
            {type}
          </FilterChip>
        ))}
      </div>
      <DataState loading={graph.loading} error={graph.error} retry={graph.reload} code={graph.errorCode}>
        {nodes.length ? (
          <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
            <svg
              viewBox={`${view.x} ${view.y} ${WIDTH / view.k} ${HEIGHT / view.k}`}
              className="h-[min(78vh,820px)] w-full cursor-grab rounded-xl border border-border bg-surface active:cursor-grabbing"
              onWheel={onWheel}
              onPointerDown={onPointerDown}
              onPointerMove={onPointerMoveSimple}
              onPointerUp={() => {
                drag.current = null;
              }}
              onPointerLeave={() => {
                drag.current = null;
              }}
            >
              {edges.map((edge) => {
                const source = layout[edge.source];
                const target = layout[edge.target];
                if (!source || !target) return null;
                const active =
                  hovered === edge.source ||
                  hovered === edge.target ||
                  selected?.id === edge.source ||
                  selected?.id === edge.target;
                return (
                  <line
                    key={`${edge.source}-${edge.target}-${edge.relation}`}
                    x1={source.x}
                    y1={source.y}
                    x2={target.x}
                    y2={target.y}
                    stroke={active ? "#2ee6c7" : "#243140"}
                    strokeWidth={active ? 1.8 : 1}
                  />
                );
              })}
              {nodes.map((node) => {
                const point = layout[node.id];
                if (!point) return null;
                const active = selected?.id === node.id || hovered === node.id;
                const label = node.label.slice(0, 22);
                const pillWidth = Math.max(56, label.length * 6.4 + 16);
                return (
                  <g
                    key={node.id}
                    data-node="true"
                    transform={`translate(${point.x},${point.y})`}
                    className="cursor-pointer"
                    onClick={() => setSelected(node)}
                    onPointerEnter={() => setHovered(node.id)}
                    onPointerLeave={() => setHovered((current) => (current === node.id ? null : current))}
                  >
                    <rect
                      x={-pillWidth / 2}
                      y={14}
                      width={pillWidth}
                      height={18}
                      rx={9}
                      fill={active ? "#15202b" : "#0e1620"}
                      stroke={COLORS[node.type] || "#8aa0b2"}
                      strokeOpacity={active ? 0.9 : 0.35}
                    />
                    <circle r={active ? 10 : 7} fill={COLORS[node.type] || "#8aa0b2"} />
                    <text y={27} textAnchor="middle" fill="#e7eef4" fontSize="10">
                      {label}
                    </text>
                  </g>
                );
              })}
            </svg>
            <aside className="rounded-xl border border-border bg-surface p-4 text-sm">
              <p className="mb-3 font-mono text-[11px] text-muted">
                {nodes.length} nodes · {edges.length} edges
                {graph.data?.truncated ? " · truncated" : ""}
              </p>
              {selected ? (
                <>
                  <p className="font-mono text-xs text-muted">{selected.id}</p>
                  <h3 className="mt-1 text-lg font-semibold">{selected.label}</h3>
                  <p className="text-muted">{selected.type}</p>
                  <dl className="mt-3 space-y-1">
                    {Object.entries(selected.properties || {})
                      .filter(([key]) => key !== "available")
                      .map(([key, value]) => (
                      <div key={key} className="flex justify-between gap-2">
                        <dt className="text-muted">{key}</dt>
                        <dd>{formatObject(value)}</dd>
                      </div>
                    ))}
                  </dl>
                  {selected.type === "Vendor" && (
                    <Link
                      className="mt-3 inline-block text-teal"
                      to={`/actors/${encodeURIComponent(String(selected.properties?.alias || selected.label))}`}
                    >
                      Open actor profile
                    </Link>
                  )}
                  {selected.type === "IntelRef" && intelIdFromGraphNode(selected) && (
                    <div className="mt-3 flex flex-col gap-2">
                      <button
                        className="text-left text-teal hover:underline"
                        onClick={() => {
                          const id = intelIdFromGraphNode(selected);
                          if (id) setDetailId(id);
                        }}
                      >
                        Open intelligence
                      </button>
                      <Link
                        className="text-teal hover:underline"
                        to={`/intel?intel_id=${encodeURIComponent(intelIdFromGraphNode(selected) || "")}`}
                      >
                        Open in intelligence desk
                      </Link>
                      {selected.properties?.available === false && (
                        <p className="text-xs text-amber-200">
                          No exact corpus match for this graph id. The drawer will resolve it if a live record exists.
                        </p>
                      )}
                    </div>
                  )}
                  {selected.type === "Neighborhood" && (
                    <Link
                      className="mt-3 inline-block text-teal"
                      to={`/intel?neighborhood=${encodeURIComponent(String(selected.properties?.name || selected.label).toLowerCase())}`}
                    >
                      Filter intel
                    </Link>
                  )}
                  {selected.type === "Product" && (
                    <Link
                      className="mt-3 inline-block text-teal"
                      to={`/search?q=${encodeURIComponent(String(selected.properties?.name || selected.label))}`}
                    >
                      Search product
                    </Link>
                  )}
                </>
              ) : (
                <EmptyState title="Select a node" detail="Scroll to zoom, drag empty space to pan." />
              )}
            </aside>
          </div>
        ) : (
          <EmptyState title="Empty graph" detail="No nodes resolved for this center. Collect intel or try another ID." />
        )}
      </DataState>
      <IntelDetailDrawer intelId={detailId} onClose={() => setDetailId(null)} />
    </div>
  );
}

function layoutForce(
  nodes: GraphNode[],
  edges: { source: string; target: string }[],
): Record<string, { x: number; y: number }> {
  const points: Record<string, { x: number; y: number; vx: number; vy: number }> = {};
  const count = Math.max(nodes.length, 1);
  const radius = Math.min(320, 90 + count * 7);
  nodes.forEach((node, index) => {
    const angle = (index / count) * Math.PI * 2;
    points[node.id] = {
      x: WIDTH / 2 + Math.cos(angle) * radius,
      y: HEIGHT / 2 + Math.sin(angle) * radius * 0.72,
      vx: 0,
      vy: 0,
    };
  });
  const minDist = Math.max(88, 240 / Math.sqrt(count));
  for (let tick = 0; tick < 180; tick += 1) {
    for (const a of nodes) {
      for (const b of nodes) {
        if (a.id === b.id) continue;
        const pa = points[a.id];
        const pb = points[b.id];
        const dx = pa.x - pb.x;
        const dy = pa.y - pb.y;
        const dist = Math.max(Math.hypot(dx, dy), 1);
        const overlap = minDist - dist;
        const force = overlap > 0 ? overlap * 0.08 : 220 / (dist * dist);
        pa.vx += (dx / dist) * force;
        pa.vy += (dy / dist) * force;
      }
    }
    for (const edge of edges) {
      const pa = points[edge.source];
      const pb = points[edge.target];
      if (!pa || !pb) continue;
      const dx = pb.x - pa.x;
      const dy = pb.y - pa.y;
      const dist = Math.max(Math.hypot(dx, dy), 1);
      const pull = (dist - 150) * 0.012;
      pa.vx += (dx / dist) * pull;
      pa.vy += (dy / dist) * pull;
      pb.vx -= (dx / dist) * pull;
      pb.vy -= (dy / dist) * pull;
    }
    for (const node of nodes) {
      const point = points[node.id];
      point.vx += (WIDTH / 2 - point.x) * 0.0014;
      point.vy += (HEIGHT / 2 - point.y) * 0.0014;
      point.x = Math.min(WIDTH - 70, Math.max(70, point.x + point.vx));
      point.y = Math.min(HEIGHT - 50, Math.max(50, point.y + point.vy));
      point.vx *= 0.78;
      point.vy *= 0.78;
    }
  }
  return Object.fromEntries(Object.entries(points).map(([id, point]) => [id, { x: point.x, y: point.y }]));
}
