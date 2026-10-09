import { useState } from "react";
import { DataState, EmptyState, PageHeader, Toast } from "../components/Ui";
import { usePrincipal } from "../lib/principal";
import { exportApi, intelApi, saveArtifact } from "../lib/api";
import { formatDate } from "../lib/formatters";
import { useApi } from "../hooks";
import type { ExportFormat } from "../types/api";

export default function ReportsPage() {
  const intel = useApi(() => intelApi.list({ limit: "50" }));
  const canExport = usePrincipal()?.role !== "viewer";
  const [toast, setToast] = useState<string | null>(null);
  const [tone, setTone] = useState<"success" | "error">("success");
  const records = intel.data?.data ?? [];
  const [selected, setSelected] = useState<string[]>([]);
  const toggle = (id: string) => {
    setSelected((current) =>
      current.includes(id) ? current.filter((item) => item !== id) : [...current, id],
    );
  };

  const download = async (format: ExportFormat, ids: string[]) => {
    if (!ids.length) {
      setTone("error");
      setToast("Nothing to export");
      return;
    }
    try {
      saveArtifact(await exportApi.report(format, ids));
      setTone("success");
      setToast(`Sealed ${format.toUpperCase()} ready`);
    } catch (error) {
      setTone("error");
      setToast(error instanceof Error ? error.message : "Export failed");
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow="EVIDENCE"
        title="Reports & export"
        description="Select records from the latest 50, or use filters on Intelligence, then download a sealed packet. The seal is the SHA-256 of the downloaded file. Exports are not a claim of legal admissibility."
      />
      <div className={canExport ? "mb-4 flex gap-2" : "hidden"}>
        {(["csv", "json", "pdf"] as ExportFormat[]).map((format) => (
          <button
            key={format}
            className="rounded border border-border px-3 py-1.5 text-xs uppercase disabled:opacity-40"
            disabled={!selected.length || intel.loading}
            onClick={() => void download(format, selected)}
          >
            Export {format}
          </button>
        ))}
      </div>
      <DataState loading={intel.loading} error={intel.error} retry={intel.reload} code={intel.errorCode}>
        {records.length ? (
          <ul className="space-y-2">
            {records.map((record) => (
              <li key={record.intel_id} className="rounded-lg border border-border bg-surface px-3 py-2 text-sm">
                <label className="inline-flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={selected.includes(record.intel_id)}
                    onChange={() => toggle(record.intel_id)}
                  />
                  <strong>{record.intel_id}</strong>
                </label>
                <span className="ml-2 text-muted">
                  {record.products.join(", ") || record.intent_label} · {formatDate(record.captured_at)}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No reportable records" detail="The corpus is empty, so sealed export is blocked." />
        )}
      </DataState>
      {toast && <Toast message={toast} tone={tone} onDismiss={() => setToast(null)} />}
    </div>
  );
}
