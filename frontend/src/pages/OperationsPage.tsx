import { DataState, EmptyState, PageHeader, Panel, SourceBadge } from "../components/Ui";
import { healthApi, operationsApi } from "../lib/api";
import { formatDate, formatRelative } from "../lib/formatters";
import { useApi } from "../hooks";
import type { Principal } from "../types/api";

export default function OperationsPage({ principal }: { principal?: Principal }) {
  const forbidden = Boolean(principal && principal.role !== "administrator");
  const health = useApi(() => healthApi.detailed());
  const sources = useApi(() => operationsApi.sources());
  const processing = useApi(() => operationsApi.processing());
  const onion = useApi(() => operationsApi.onionReview());
  const audit = useApi(() => operationsApi.audit(30));
  const runs = useApi(() => operationsApi.collectionRuns(40));

  if (forbidden) {
    return (
      <div>
        <PageHeader
          eyebrow="OPERATIONS"
          title="System status"
          description="This desk is administrator-only."
        />
        <EmptyState
          title="Access denied"
          detail="A viewer or analyst token cannot load collection runs, audit, or source registry."
        />
      </div>
    );
  }

  return (
    <div>
      <PageHeader
        eyebrow="OPERATIONS"
        title="System status"
        description="Datastore health, public source registry, and collector history. Telegram and onion stay CLI-gated."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Datastore health">
          <DataState loading={health.loading} error={health.error} retry={health.reload} code={health.errorCode}>
            <ul className="space-y-2 text-sm">
              {Object.entries(health.data?.services ?? {}).map(([name, service]) => (
                <li key={name} className="flex justify-between">
                  <span>{name}</span>
                  <span className="font-mono text-muted">
                    {service.status}
                    {service.latency_ms != null ? ` · ${service.latency_ms}ms` : ""}
                    {service.last_started_at ? ` · ${formatRelative(service.last_started_at)}` : ""}
                  </span>
                </li>
              ))}
            </ul>
          </DataState>
        </Panel>
        <Panel title="Processing">
          <DataState
            loading={processing.loading}
            error={processing.error}
            retry={processing.reload}
            code={processing.errorCode}
          >
            <ul className="space-y-1 text-sm">
              {Object.entries(processing.data?.data ?? {}).map(([status, count]) => (
                <li key={status} className="flex justify-between">
                  <span>{status}</span>
                  <span className="font-mono">{count}</span>
                </li>
              ))}
            </ul>
          </DataState>
        </Panel>
        <Panel title="Source registry" className="lg:col-span-2">
          <DataState loading={sources.loading} error={sources.error} retry={sources.reload} code={sources.errorCode}>
            <ul className="space-y-2 text-sm">
              {(sources.data?.data ?? []).map((source) => (
                <li key={source.source_id} className="flex items-center justify-between">
                  <span>
                    {source.source_id} <SourceBadge source={source.source_class} />
                  </span>
                  <span className="text-muted">{source.enabled ? "enabled" : "disabled"}</span>
                </li>
              ))}
            </ul>
          </DataState>
        </Panel>
        <Panel title="Collection runs" className="lg:col-span-2">
          <DataState loading={runs.loading} error={runs.error} retry={runs.reload} code={runs.errorCode}>
            {(runs.data?.data ?? []).length ? (
              <ul className="space-y-2 text-sm">
                {(runs.data?.data ?? []).map((run, index) => (
                  <li key={`${run.source_id}-${run.started_at}-${index}`} className="flex justify-between">
                    <span>
                      {run.source_id} · published {run.published ?? 0} · dup {run.duplicates ?? 0}
                    </span>
                    <span className="font-mono text-xs text-muted">
                      {formatDate(run.started_at)} {run.failure_code || ""}
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState
                title="Collector has never succeeded"
                detail="The Railway collector loop writes history here after the first cycle."
              />
            )}
          </DataState>
        </Panel>
        <Panel title="Onion review">
          <DataState loading={onion.loading} error={onion.error} retry={onion.reload} code={onion.errorCode}>
            <p className="text-sm text-muted">{onion.data?.data.policy}</p>
            <p className="mt-2 font-mono text-xs">
              reviewed {onion.data?.data.reviewed_source_count ?? 0} · enabled{" "}
              {onion.data?.data.approved_enabled_count ?? 0}
            </p>
          </DataState>
        </Panel>
        <Panel title="Audit">
          <DataState loading={audit.loading} error={audit.error} retry={audit.reload} code={audit.errorCode}>
            <ul className="max-h-64 space-y-1 overflow-y-auto text-xs">
              {(audit.data?.data ?? []).map((event, index) => (
                <li key={`${event.occurred_at}-${index}`}>
                  {event.actor} {event.action} · {formatDate(event.occurred_at)}
                </li>
              ))}
            </ul>
          </DataState>
        </Panel>
      </div>
    </div>
  );
}
