import type { GraphNode } from "../types/api";

export function resolveIntelId(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (!trimmed) return null;
  return trimmed.replace(/^intel:/i, "").trim() || null;
}

export function intelIdFromGraphNode(node: GraphNode): string | null {
  const fromProps = resolveIntelId(String(node.properties?.intel_id || ""));
  if (fromProps) return fromProps;
  if (node.id.toLowerCase().startsWith("intel:")) return resolveIntelId(node.id);
  if (node.type === "IntelRef") return resolveIntelId(node.label);
  return null;
}

export function sourceLabel(value?: string | null): string {
  return (value || "unknown").replaceAll("_", " ");
}
