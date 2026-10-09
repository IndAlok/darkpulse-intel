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
import { usePrincipal } from "../lib/principal";
import { alertsApi, wsUrl } from "../lib/api";
import { formatDate } from "../lib/formatters";
import { useApi } from "../hooks";
import type { AlertRule } from "../types/api";

export default function AlertsPage() {
  const history = useApi(() => alertsApi.history());
  const config = useApi(() => alertsApi.config());
  const [live, setLive] = useState<"connecting" | "connected" | "down" | "refused">(
    "connecting",
  );
  const [toast, setToast] = useState<string | null>(null);
  const [draft, setDraft] = useState<AlertRule>({
    name: "",
    severity_min: 60,
    products: [],
    neighborhoods: [],
    enabled: true,
  });
  const [confirm, setConfirm] = useState<AlertRule[] | null>(null);
  const [saving, setSaving] = useState(false);
  const rulesReady = !config.loading && !config.error && config.data != null;
  const canWrite = usePrincipal()?.role !== "viewer";

  const reloadHistory = history.reload;
  useEffect(() => {
    let socket: WebSocket | null = null;
    let closed = false;
    let retry: number | undefined;
    let ping: number | undefined;
    let delay = 1000;
    const connect = async () => {
      let ticket: string;
      try {
        ticket = (await alertsApi.ticket()).data.ticket;
      } catch {
        if (!closed) {
          setLive("down");
          retry = window.setTimeout(() => void connect(), delay);
          delay = Math.min(delay * 2, 30000);
        }
        return;
      }
      if (closed) return;
      socket = new WebSocket(wsUrl(ticket));
      socket.onopen = () => {
        delay = 1000;
        setLive("connected");
        ping = window.setInterval(() => socket?.send("ping"), 25000);
      };
      socket.onmessage = () => {
        void reloadHistory();
      };
      socket.onclose = (event) => {
        window.clearInterval(ping);
        setLive(event.code === 1008 ? "refused" : "down");
        if (!closed && event.code !== 1008) {
          retry = window.setTimeout(() => void connect(), delay);
          delay = Math.min(delay * 2, 30000);
        }
      };
    };
    void connect();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      window.clearInterval(ping);
      socket?.close();
    };
  }, [reloadHistory]);

  const saveRules = async (rules: AlertRule[]) => {
    if (!rulesReady || saving) return;
    setSaving(true);
    try {
      await alertsApi.updateConfig(rules);
      await config.reload();
      setToast("Alert rules updated");
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Unable to save rules");
    } finally {
      setSaving(false);
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
                  value={draft.products.join(", ")}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      products: event.target.value.split(",").map((item) => item.trim()).filter(Boolean),
                    })
                  }
                />
                <input
                  className="rounded border border-border bg-bg px-3 py-2 text-sm"
                  placeholder="Neighborhoods, comma separated"
                  value={draft.neighborhoods.join(", ")}
                  onChange={(event) =>
                    setDraft({
                      ...draft,
                      neighborhoods: event.target.value.split(",").map((item) => item.trim()).filter(Boolean),
                    })
                  }
                />
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={draft.enabled}
                    onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })}
                  />
                  Enabled
                </label>
                <button
                  className="rounded bg-teal px-3 py-2 text-sm text-bg disabled:opacity-40"
                  disabled={!canWrite || !rulesReady || saving}
                  onClick={() => {
                    if (!rulesReady || !draft.name.trim()) return;
                    setConfirm([...(config.data?.data.rules ?? []), draft]);
                  }}
                >
                  Add rule
                </button>
              </div>
              <ul className="space-y-2 text-sm">
                {(config.data?.data.rules ?? []).map((rule) => (
                  <li key={rule.name} className="flex items-center justify-between">
                    <span>
                      {rule.name} · min {rule.severity_min}
                      {rule.products.length ? ` · ${rule.products.join(", ")}` : ""}
                      {rule.neighborhoods.length ? ` · ${rule.neighborhoods.join(", ")}` : ""}
                      {rule.enabled ? "" : " · disabled"}
                    </span>
                    <span className="flex gap-3">
                      <button
                        className="text-xs text-teal disabled:opacity-40"
                        disabled={!canWrite || !rulesReady || saving}
                        onClick={() => {
                          if (!rulesReady) return;
                          setDraft({
                            name: rule.name,
                            severity_min: rule.severity_min,
                            products: rule.products,
                            neighborhoods: rule.neighborhoods,
                            enabled: rule.enabled,
                          });
                        }}
                      >
                        Load into editor
                      </button>
                      <button
                        className="text-red-300 disabled:opacity-40"
                        disabled={!canWrite || !rulesReady || saving}
                        onClick={() => {
                          if (!rulesReady) return;
                          setConfirm((config.data?.data.rules ?? []).filter((item) => item.name !== rule.name));
                        }}
                      >
                        Remove
                      </button>
                    </span>
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
          if (confirm && rulesReady && !saving) void saveRules(confirm);
          setConfirm(null);
        }}
      />
      {toast && <Toast message={toast} onDismiss={() => setToast(null)} />}
    </div>
  );
}
