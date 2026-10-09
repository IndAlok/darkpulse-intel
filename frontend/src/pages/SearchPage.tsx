import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import IntelDetailDrawer from "../components/IntelDetailDrawer";
import {
  Confidence,
  DataState,
  EmptyState,
  PageHeader,
  SeverityBadge,
  SourceBadge,
} from "../components/Ui";
import { intelApi, searchApi } from "../lib/api";
import { formatDate } from "../lib/formatters";
import { useApi, useDebouncedValue } from "../hooks";

const LANGS = ["", "en", "hi", "gu", "hinglish", "mr", "ur"];

export default function SearchPage() {
  const [params, setParams] = useSearchParams();
  const [detailId, setDetailId] = useState<string | null>(null);
  const q = params.get("q") || "";
  const lang = params.get("lang") || "";
  const debounced = useDebouncedValue(`${q}|${lang}`);
  const [query, language] = debounced.split("|");
  const searched = useApi(
    () => (query ? searchApi.search(query, language || undefined) : Promise.resolve(null)),
    debounced,
  );
  const recent = useApi(
    () => (query ? Promise.resolve(null) : intelApi.list({ limit: "12" })),
    debounced,
  );
  const loading = query ? searched.loading : recent.loading;
  const error = query ? searched.error : recent.error;
  const errorCode = query ? searched.errorCode : recent.errorCode;
  const reload = query ? searched.reload : recent.reload;
  const cards = useMemo(() => {
    if (query) {
      return (searched.data?.data ?? []).map((record) => ({
        id: record.intel_id,
        products:
          record.products?.map((product) => product.canonical || product.raw_term).filter(Boolean).join(", ") ||
          record.intent?.label ||
          "Unspecified indicator",
        excerpt: record.evidence_snapshot?.excerpt || record.translated_text || "",
        band: record.severity?.band || "info",
        neighborhood: record.geo?.neighborhood,
        source: record.source_class || "unknown",
        captured: record.captured_at,
        confidence: record.confidence ?? 0,
      }));
    }
    return (recent.data?.data ?? []).map((item) => ({
      id: item.intel_id,
      products: item.products.join(", ") || item.intent_label || "Unspecified indicator",
      excerpt: item.vendor_aliases.join(", "),
      band: item.severity_band || "info",
      neighborhood: item.neighborhood,
      source: item.source_class || "unknown",
      captured: item.captured_at,
      confidence: item.confidence ?? 0,
    }));
  }, [query, recent.data, searched.data]);

  return (
    <div>
      <PageHeader
        eyebrow="INVESTIGATE"
        title="Search"
        description="Language-aligned search. An empty box shows the latest sanitized records."
      />
      <div className="mb-4 flex flex-wrap gap-2">
        <input
          className="min-w-64 flex-1 rounded border border-border bg-surface px-3 py-2 text-sm"
          value={q}
          onChange={(event) => {
            const next = new URLSearchParams(params);
            if (event.target.value) next.set("q", event.target.value);
            else next.delete("q");
            setParams(next);
          }}
          placeholder="Search terms, slang, or products"
        />
        <select
          className="rounded border border-border bg-surface px-3 py-2 text-sm"
          value={lang}
          onChange={(event) => {
            const next = new URLSearchParams(params);
            if (event.target.value) next.set("lang", event.target.value);
            else next.delete("lang");
            setParams(next);
          }}
        >
          {LANGS.map((item) => (
            <option key={item || "all"} value={item}>
              {item || "All languages"}
            </option>
          ))}
        </select>
      </div>
      <DataState loading={loading} error={error} retry={reload} code={errorCode}>
        {cards.length ? (
          <div className="grid gap-3 md:grid-cols-2">
            {cards.map((card) => (
              <button
                key={card.id}
                className="rounded-xl border border-border bg-surface p-4 text-left hover:border-teal/40"
                onClick={() => setDetailId(card.id)}
              >
                <div className="mb-2 flex items-center justify-between">
                  <SeverityBadge band={card.band} />
                  <SourceBadge source={card.source} />
                </div>
                <h3 className="text-sm font-medium">{card.products}</h3>
                {card.excerpt ? (
                  <p className="mt-1 line-clamp-2 text-xs text-navy">{card.excerpt}</p>
                ) : null}
                <p className="mt-1 text-xs text-muted">
                  {card.neighborhood || "Location pending"} · {formatDate(card.captured)}
                </p>
                <Confidence value={card.confidence} />
              </button>
            ))}
          </div>
        ) : (
          <EmptyState
            title={query ? "No matches" : "No intelligence yet"}
            detail={
              query
                ? "The search index returned no sanitized records."
                : "Published records appear here before a query is entered."
            }
          />
        )}
      </DataState>
      <IntelDetailDrawer intelId={detailId} onClose={() => setDetailId(null)} />
    </div>
  );
}
