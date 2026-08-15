import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ConfirmationDialog,
  DataState,
  DataTable,
  EmptyState,
  PageHeader,
  Toast,
} from "../components/Ui";
import { alertsApi, wsUrl } from "../lib/api";
import { formatDate } from "../lib/formatters";
import { useApi } from "../hooks";
import type { AlertRule } from "../types/api";

export default function AlertsPage() {
  const history = useApi(() => alertsApi.history());
  const config = useApi(() => alertsApi.config());
  const [live, setLive] = useState<"connecting" | "connected" | "down">("connecting");
  const [toast, setToast] = useState<string | null>(null);
  const [draft, setDraft] = useState<AlertRule>({
    name: "",
    severity_min: 60,
    products: [],
    neighborhoods: [],
    enabled: true,
  });
  const [confirm, setConfirm] = useState<AlertRule[] | null>(null);

  useEffect(() => {
    let socket: WebSocket | null = null;
    try {
      socket = new WebSocket(wsUrl());
      socket.onopen = () => setLive("connected");
      socket.onclose = () => setLive("down");
      socket.onerror = () => setLive("down");
      socket.onmessage = () => {
        void history.reload();
      };
    } catch {
      setLive("down");
    }
    return () => socket?.close();
  }, [history.reload]);

  const saveRules = async (rules: AlertRule[]) => {
    try {
      await alertsApi.updateConfig(rules);
      await config.reload();
      setToast("Alert rules updated");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Unable to save rules");
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow="MONITOR"
        title="Alerts"
        description="Acknowledge, assign, and edit rules. The live badge reflects the actual WebSocket."
        action={
          <span
            className={`rounded-full px-3 py-1 font-mono text-xs ${
              live === "connected" ? "bg-teal/15 text-teal" : "bg-amber-500/15 text-amber-200"
            }`}
          >
            WS {live}
          </span>
        }
      />
      <DataState loading={history.loading} error={history.error} retry={history.reload} code={history.errorCode}>
        {(history.data?.data ?? []).length ? (
          <DataTable columns={["Rule", "Intel", "Score", "When", "Status", "Actions"]}>
            {(history.data?.data ?? []).map((alert) => (
              <tr key={alert.id}>
                <td className="px-3 py-2">{alert.rule_name}</td>
                <td className="px-3 py-2">
                  <Link className="text-teal" to={`/intel?intel_id=${encodeURIComponent(alert.intel_id)}`}>
                    {alert.intel_id}
                  </Link>
                </td>
                <td className="px-3 py-2 font-mono">{alert.severity_score}</td>
                <td className="px-3 py-2 text-xs text-muted">{formatDate(alert.triggered_at)}</td>
                <td className="px-3 py-2 text-xs">
                  {alert.resolved_at ? "resolved" : alert.acknowledged ? "acked" : "open"}
                  {alert.assignee ? ` · ${alert.assignee}` : ""}
                </td>
                <td className="px-3 py-2">
                  <button
                    className="mr-2 text-xs text-teal"
                    onClick={() =>
                      void alertsApi
                        .patch(alert.id, { acknowledged: true })
                        .then(() => history.reload())
                        .catch((error: Error) => setToast(error.message))
                    }
                  >
                    Ack
                  </button>
                  <button
                    className="text-xs text-navy"
                    onClick={() => {
                      const assignee = window.prompt("Assignee", alert.assignee || "") || undefined;
                      if (!assignee) return;
                      void alertsApi
                        .patch(alert.id, { assignee, resolved: true })
                        .then(() => history.reload())
                        .catch((error: Error) => setToast(error.message));
                    }}
                  >
                    Assign
                  </button>
                </td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState title="No alert history" detail="Rules fire when processed intel matches." />
        )}
      </DataState>
      <section className="mt-6 rounded-xl border border-border bg-surface p-4">
        <h2 className="mb-3 text-sm font-semibold">Rule editor</h2>
        <div className="mb-3 grid gap-2 md:grid-cols-4">
          <input
            className="rounded border border-border bg-bg px-3 py-2 text-sm"
            placeholder="Rule name"
            value={draft.name}
            onChange={(event) => setDraft({ ...draft, name: event.target.value })}
          />
          <input
            type="number"
            className="rounded border border-border bg-bg px-3 py-2 text-sm"
            value={draft.severity_min}
            onChange={(event) => setDraft({ ...draft, severity_min: Number(event.target.value) })}
          />
          <input
            className="rounded border border-border bg-bg px-3 py-2 text-sm"
            placeholder="Products, comma separated"
            onChange={(event) =>
              setDraft({
                ...draft,
                products: event.target.value.split(",").map((item) => item.trim()).filter(Boolean),
              })
            }
          />
          <button
            className="rounded bg-teal px-3 py-2 text-sm text-bg"
            onClick={() => {
              if (!draft.name.trim()) return;
              setConfirm([...(config.data?.data.rules ?? []), draft]);
            }}
          >
            Add rule
          </button>
        </div>
        <ul className="space-y-2 text-sm">
          {(config.data?.data.rules ?? []).map((rule) => (
            <li key={rule.name} className="flex justify-between">
              <span>
                {rule.name} · min {rule.severity_min}
              </span>
              <button
                className="text-red-300"
                onClick={() =>
                  setConfirm((config.data?.data.rules ?? []).filter((item) => item.name !== rule.name))
                }
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      </section>
      <ConfirmationDialog
        open={Boolean(confirm)}
        title="Update alert rules"
        detail="This writes the analyst-controlled alert configuration."
        onClose={() => setConfirm(null)}
        onConfirm={() => {
          if (confirm) void saveRules(confirm);
          setConfirm(null);
        }}
      />
      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  );
}
