import { Download } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import IntelDetailDrawer from "../components/IntelDetailDrawer";
import {
  Confidence,
  DataState,
  DataTable,
  EmptyState,
  PageHeader,
  Pagination,
  SeverityBadge,
  SourceBadge,
  Toast,
} from "../components/Ui";
import { exportApi, intelApi } from "../lib/api";
import { formatDate } from "../lib/formatters";
import { resolveIntelId } from "../lib/intel";
import { useApi, useDebouncedValue } from "../hooks";
import type { ExportFormat } from "../types/api";

const FILTERS = [
  "q",
  "intel_id",
  "product",
  "neighborhood",
  "severity_min",
  "band",
  "source_class",
  "vendor",
  "date_from",
  "date_to",
  "cursor",
] as const;

export default function IntelFeedPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [selected, setSelected] = useState<string[]>([]);
  const [detailId, setDetailId] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [tone, setTone] = useState<"success" | "error">("success");
  const [cursorStack, setCursorStack] = useState<string[]>([]);
  const filters = useMemo(
    () =>
      Object.fromEntries(
        FILTERS.map((key) => [key, searchParams.get(key) || ""]).filter(([, value]) => value),
      ) as Record<string, string>,
    [searchParams],
  );
  const requestFilters = useMemo(
    () => ({ ...filters, limit: searchParams.get("limit") || "25" }),
    [filters, searchParams],
  );
  const debounced = useDebouncedValue(JSON.stringify(requestFilters));
  const feed = useApi(() => intelApi.list(JSON.parse(debounced) as Record<string, string>), debounced);
  const records = feed.data?.data ?? [];
  useEffect(() => {
    const id = resolveIntelId(searchParams.get("intel_id"));
    if (id) setDetailId(id);
  }, [searchParams]);
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("cursor");
    setCursorStack([]);
    setSearchParams(next);
  };

  const exportSelected = async (format: ExportFormat) => {
    if (!selected.length) {
      setTone("error");
      setMessage("Select at least one record to export");
      return;
    }
    try {
      const artifact = await exportApi.report(format, selected);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(artifact.blob);
      link.download = artifact.filename;
      link.click();
      URL.revokeObjectURL(link.href);
      setTone("success");
      setMessage(`Exported ${selected.length} records`);
    } catch (error) {
      setTone("error");
      setMessage(error instanceof Error ? error.message : "Export failed");
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow="INVESTIGATE"
        title="Intelligence"
        description="URL-backed filters over sanitized TraffickingIntel summaries."
        action={
          <div className="flex gap-2">
            {(["csv", "json", "pdf"] as ExportFormat[]).map((format) => (
              <button
                key={format}
                className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-xs uppercase"
                onClick={() => void exportSelected(format)}
              >
                <Download size={13} /> {format}
              </button>
            ))}
          </div>
        }
      />
      <div className="mb-4 grid gap-2 md:grid-cols-4">
        <input
          className="rounded border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Keyword"
          value={searchParams.get("q") || ""}
          onChange={(event) => setFilter("q", event.target.value)}
        />
        <input
          className="rounded border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Neighborhood"
          value={searchParams.get("neighborhood") || ""}
          onChange={(event) => setFilter("neighborhood", event.target.value)}
        />
        <input
          className="rounded border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Product"
          value={searchParams.get("product") || ""}
          onChange={(event) => setFilter("product", event.target.value)}
        />
        <select
          className="rounded border border-border bg-surface px-3 py-2 text-sm"
          value={searchParams.get("band") || ""}
          onChange={(event) => setFilter("band", event.target.value)}
        >
          <option value="">All bands</option>
          {["info", "low", "medium", "high", "critical"].map((band) => (
            <option key={band} value={band}>
              {band}
            </option>
          ))}
        </select>
      </div>
      <DataState loading={feed.loading} error={feed.error} retry={feed.reload} code={feed.errorCode}>
        {records.length ? (
          <DataTable columns={["", "Severity", "Intent", "Products", "Place", "Source", "When"]}>
            {records.map((record) => (
              <tr
                key={record.intel_id}
                className="cursor-pointer hover:bg-raised"
                onClick={() => setDetailId(record.intel_id)}
              >
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(record.intel_id)}
                    onClick={(event) => event.stopPropagation()}
                    onChange={() =>
                      setSelected((current) =>
                        current.includes(record.intel_id)
                          ? current.filter((id) => id !== record.intel_id)
                          : [...current, record.intel_id],
                      )
                    }
                  />
                </td>
                <td className="px-3 py-2">
                  <SeverityBadge band={record.severity_band} />
                </td>
                <td className="px-3 py-2">{record.intent_label}</td>
                <td className="px-3 py-2">{record.products.join(", ") || "—"}</td>
                <td className="px-3 py-2">{record.neighborhood || "—"}</td>
                <td className="px-3 py-2">
                  <SourceBadge source={record.source_class || "unknown"} />
                </td>
                <td className="px-3 py-2 font-mono text-xs text-muted">
                  {formatDate(record.captured_at)}
                  <Confidence value={record.confidence} />
                </td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState
            title="No matching intelligence"
            detail={
              searchParams.get("intel_id")
                ? "This identifier does not match a live record. The graph reference may be stale."
                : "Adjust filters or wait for the next collector cycle."
            }
          />
        )}
        <Pagination
          hasPrevious={cursorStack.length > 0}
          hasNext={Boolean(feed.data?.pagination?.cursor)}
          onPrevious={() => {
            const next = new URLSearchParams(searchParams);
            const previous = cursorStack[cursorStack.length - 1];
            setCursorStack((stack) => stack.slice(0, -1));
            if (previous) next.set("cursor", previous);
            else next.delete("cursor");
            setSearchParams(next);
          }}
          onNext={() => {
            const cursor = feed.data?.pagination?.cursor;
            if (!cursor) return;
            setCursorStack((stack) => [...stack, searchParams.get("cursor") || ""]);
            const next = new URLSearchParams(searchParams);
            next.set("cursor", cursor);
            setSearchParams(next);
          }}
        />
      </DataState>
      <IntelDetailDrawer
        intelId={detailId}
        onClose={() => {
          setDetailId(null);
          if (searchParams.get("intel_id")) {
            const next = new URLSearchParams(searchParams);
            next.delete("intel_id");
            setSearchParams(next);
          }
        }}
      />
      {message && <Toast message={message} tone={tone} onDismiss={() => setMessage(null)} />}
    </div>
  );
}
