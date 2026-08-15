import { useState } from "react";
import { DataState, EmptyState, PageHeader, Toast } from "../components/Ui";
import { exportApi, intelApi } from "../lib/api";
import { formatDate } from "../lib/formatters";
import { useApi } from "../hooks";
import type { ExportFormat } from "../types/api";

export default function ReportsPage() {
  const intel = useApi(() => intelApi.list({ limit: "12" }));
  const [toast, setToast] = useState<string | null>(null);
  const [tone, setTone] = useState<"success" | "error">("success");
  const records = intel.data?.data ?? [];

  const download = async (format: ExportFormat, ids: string[]) => {
    if (!ids.length) {
      setTone("error");
      setToast("Nothing to export");
      return;
    }
    try {
      const artifact = await exportApi.report(format, ids);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(artifact.blob);
      link.download = artifact.filename;
      link.click();
      URL.revokeObjectURL(link.href);
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
        description="Preview recent records, then download a sealed packet. Exports are not a claim of legal admissibility."
      />
      <div className="mb-4 flex gap-2">
        {(["csv", "json", "pdf"] as ExportFormat[]).map((format) => (
          <button
            key={format}
            className="rounded border border-border px-3 py-1.5 text-xs uppercase"
            onClick={() => void download(format, records.map((record) => record.intel_id))}
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
                <strong>{record.intel_id}</strong>
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
