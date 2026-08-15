import { Download, Languages, MapPin, ShieldCheck } from "lucide-react";
import { Link } from "react-router-dom";
import { exportApi, intelApi } from "../lib/api";
import { formatDate, formatObject } from "../lib/formatters";
import { useApi } from "../hooks";
import {
  Confidence,
  DataState,
  Drawer,
  EvidenceCard,
  EmptyState,
  SeverityBadge,
  Timeline,
  Toast,
} from "./Ui";
import { useState } from "react";

export default function IntelDetailDrawer({
  intelId,
  onClose,
}: {
  intelId: string | null;
  onClose: () => void;
}) {
  const detail = useApi(
    () => (intelId ? intelApi.get(intelId) : Promise.resolve(null)),
    intelId,
  );
  const evidence = useApi(
    () => (intelId ? intelApi.evidence(intelId) : Promise.resolve(null)),
    intelId,
  );
  const record = detail.data?.data;
  const [toast, setToast] = useState<string | null>(null);
  const download = async () => {
    if (!intelId) return;
    try {
      const artifact = await exportApi.report("pdf", [intelId]);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(artifact.blob);
      link.download = artifact.filename;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Export failed");
    }
  };
  const products =
    record?.products
      ?.map((product) => product.canonical || product.raw_term)
      .filter(Boolean)
      .join(", ") || "Unspecified indicator";
  return (
    <Drawer open={Boolean(intelId)} title="Intelligence detail" onClose={onClose}>
      <DataState
        loading={detail.loading}
        error={detail.error}
        retry={detail.reload}
        code={detail.errorCode}
      >
        {record ? (
          <div className="space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <SeverityBadge band={record.severity?.band || "info"} />
                <h3 className="mt-2 text-lg font-semibold text-ink">{products}</h3>
                <p className="mt-1 text-sm text-muted">
                  {record.intent?.label || "unknown"} intent ·{" "}
                  <Confidence value={record.confidence ?? 0} />
                </p>
              </div>
              <button
                className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-sm text-ink"
                onClick={() => void download()}
              >
                <Download size={15} /> Export
              </button>
            </div>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <span className="text-muted">Captured</span>
                <p>{formatDate(record.captured_at)}</p>
              </div>
              <div>
                <span className="text-muted">Neighborhood</span>
                <p className="inline-flex items-center gap-1">
                  <MapPin size={13} /> {record.geo?.neighborhood || "Pending"}
                </p>
              </div>
            </div>
            <section>
              <h4 className="mb-2 text-xs tracking-wider text-muted uppercase">Severity factors</h4>
              <dl className="space-y-1 text-sm">
                {Object.entries(record.severity?.factors || {}).map(([key, value]) => (
                  <div key={key} className="flex justify-between gap-3">
                    <dt className="text-muted">{key.replaceAll("_", " ")}</dt>
                    <dd className="text-right text-ink">{formatObject(value)}</dd>
                  </div>
                ))}
                {!record.severity?.factors && <p className="text-muted">No factor breakdown</p>}
              </dl>
            </section>
            <section>
              <h4 className="mb-2 inline-flex items-center gap-1 text-xs tracking-wider text-muted uppercase">
                <Languages size={12} /> Slang
              </h4>
              <div className="flex flex-wrap gap-2">
                {(record.slang_decoded || []).map((item) => (
                  <span key={item.term} className="rounded bg-raised px-2 py-1 text-xs">
                    {item.term}
                    {item.meaning ? ` → ${item.meaning}` : ""}
                  </span>
                ))}
                {!record.slang_decoded?.length && <span className="text-sm text-muted">None decoded</span>}
              </div>
            </section>
            <section>
              <h4 className="mb-2 text-xs tracking-wider text-muted uppercase">Entities</h4>
              <p className="text-sm text-ink">
                Vendors:{" "}
                {(record.entities?.vendors || [])
                  .map((vendor) => vendor.alias)
                  .filter(Boolean)
                  .join(", ") || "None"}
              </p>
            </section>
            <DataState
              loading={evidence.loading}
              error={evidence.error}
              retry={evidence.reload}
              code={evidence.errorCode}
            >
              {evidence.data?.data ? (
                <EvidenceCard
                  title="Redacted excerpt"
                  source={record.source_class || "unknown"}
                  excerpt={evidence.data.data.excerpt || "No excerpt retained"}
                  meta={
                    <span className="inline-flex items-center gap-1">
                      <ShieldCheck size={12} /> snapshot
                    </span>
                  }
                />
              ) : (
                <EmptyState title="No excerpt" detail="Evidence snapshot is not available." />
              )}
            </DataState>
            <Timeline
              items={[
                {
                  title: record.intel_id,
                  detail: record.ingest_id,
                  time: formatDate(record.captured_at),
                },
              ]}
            />
            <Link
              to={`/graph?center=intel:${record.intel_id}`}
              className="inline-flex text-sm text-teal hover:underline"
            >
              Open in graph
            </Link>
          </div>
        ) : (
          <EmptyState
            title="Record unavailable"
            detail="This identifier does not match a live intelligence record. The graph reference may be stale."
          />
        )}
      </DataState>
      {toast && <Toast message={toast} tone="error" onDismiss={() => setToast(null)} />}
    </Drawer>
  );
}
