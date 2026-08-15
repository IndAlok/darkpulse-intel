export function formatDate(value?: string | null): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

export function formatRelative(value?: string | null): string {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "unknown";
  const delta = Date.now() - date.getTime();
  const minutes = Math.round(delta / 60000);
  if (Math.abs(minutes) < 1) return "just now";
  if (Math.abs(minutes) < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 48) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function formatScore(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "—";
  return value <= 1 ? `${Math.round(value * 100)}` : `${Math.round(value)}`;
}

export function formatBand(band?: string | null): string {
  return (band || "info").replaceAll("_", " ");
}

export function formatObject(value: unknown): string {
  if (value == null) return "—";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map((item) => formatObject(item)).filter(Boolean).join(", ") || "—";
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (record.canonical) return String(record.canonical);
    if (record.name) return String(record.name);
    if (record.label) return String(record.label);
    return Object.entries(record)
      .filter(([, item]) => item != null && item !== "")
      .map(([key, item]) => `${key.replaceAll("_", " ")}: ${formatObject(item)}`)
      .join(" · ");
  }
  return "—";
}

export function titleCase(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (char) => char.toUpperCase());
}
