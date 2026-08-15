import { Activity, AlertCircle, MapPinned, Radio } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { alertsApi, dashboardApi, healthApi, intelApi, operationsApi } from "../lib/api";
import { formatDate, formatRelative, titleCase } from "../lib/formatters";
import { sourceLabel } from "../lib/intel";
import { useApi } from "../hooks";
import {
  DataState,
  EmptyState,
  FilterChip,
  PageHeader,
  Panel,
  SeverityBadge,
  SourceBadge,
} from "../components/Ui";
import type { Principal } from "../types/api";

const PERIODS = [
  { id: "7d", label: "7 days" },
  { id: "30d", label: "30 days" },
  { id: "90d", label: "90 days" },
] as const;

export default function DashboardPage({ principal }: { principal?: Principal }) {
  const [period, setPeriod] = useState<(typeof PERIODS)[number]["id"]>("30d");
  const intel = useApi(() => intelApi.list({ limit: "8" }));
  const review = useApi(() => intelApi.list({ severity_min: "60", limit: "8" }));
  const trends = useApi(() => dashboardApi.trends(period), period);
  const sources = useApi(() => dashboardApi.sources());
  const geo = useApi(() => dashboardApi.geo());
  const alerts = useApi(() => alertsApi.history());
  const health = useApi(() => healthApi.detailed());
  const runs = useApi(
    () =>
      principal?.role === "administrator"
        ? operationsApi.collectionRuns(5)
        : Promise.resolve({ data: [] as never[] }),
    principal?.role,
  );
  const records = intel.data?.data ?? [];
  const reviewRecords = review.data?.data ?? [];
  const trendPoints = trends.data?.data;
  const openAlerts = (alerts.data?.data ?? []).filter((item) => !item.acknowledged && !item.resolved_at);
  const lastRun = runs.data?.data?.[0];
  const collector = health.data?.services?.collector;
  const chart = useMemo(
    () =>
      (trendPoints ?? []).map((point) => ({
        date: formatChartDate(point.date),
        records: point.count,
      })),
    [trendPoints],
  );
  const apiState = health.loading
    ? "Checking API"
    : health.data?.status === "healthy"
      ? "All systems healthy"
      : health.data
        ? "Systems degraded"
        : "API status unknown";

  return (
    <div>
      <PageHeader
        eyebrow="OVERVIEW"
        title="Command center"
        description="Live operating picture from collected public OSINT. Totals, trends, and queues update as the collector publishes records."
        action={
          <span
            className={`rounded-full px-3 py-1 font-mono text-xs ${
              health.data?.status === "healthy" ? "bg-teal/15 text-teal" : "bg-amber-500/15 text-amber-200"
            }`}
          >
            {apiState}
          </span>
        }
      />
      <div className="mb-5 grid gap-3 md:grid-cols-4">
        <Metric
          icon={<Activity size={16} />}
          label="Intel records"
          value={intel.data?.pagination?.total ?? "—"}
          detail="Sanitized records in the live corpus"
        />
        <Metric
          icon={<AlertCircle size={16} />}
          label="Open alerts"
          value={alerts.loading ? "—" : openAlerts.length}
          detail={`${alerts.data?.data.length ?? 0} in recent history`}
        />
        <Metric
          icon={<MapPinned size={16} />}
          label="Neighbourhoods"
          value={geo.data?.data.length ?? "—"}
          detail="Places with geo-tagged intelligence"
        />
        <Metric
          icon={<Radio size={16} />}
          label="Collector"
          value={
            lastRun
              ? formatRelative(lastRun.started_at)
              : titleCase(collector?.status || "unknown")
          }
          detail={
            lastRun
              ? `${lastRun.published ?? 0} published from ${lastRun.source_id}`
              : "No successful collection run recorded"
          }
        />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Panel title="Intelligence volume" className="xl:col-span-2" kicker={period}>
          <div className="mb-3 flex flex-wrap gap-2">
            {PERIODS.map((item) => (
              <FilterChip key={item.id} active={period === item.id} onClick={() => setPeriod(item.id)}>
                {item.label}
              </FilterChip>
            ))}
          </div>
          <DataState loading={trends.loading} error={trends.error} retry={trends.reload} code={trends.errorCode}>
            {chart.length ? (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={chart} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                    <CartesianGrid stroke="#243140" vertical={false} />
                    <XAxis dataKey="date" stroke="#8aa0b2" fontSize={11} tickLine={false} />
                    <YAxis
                      stroke="#8aa0b2"
                      fontSize={11}
                      allowDecimals={false}
                      tickLine={false}
                      width={36}
                      label={{ value: "Records", angle: -90, position: "insideLeft", fill: "#8aa0b2", fontSize: 10 }}
                    />
                    <Tooltip
                      contentStyle={{ background: "#15202b", border: "1px solid #243140", color: "#e7eef4" }}
                      labelStyle={{ color: "#8aa0b2" }}
                      formatter={(value) => [value, "Intel records"]}
                    />
                    <Legend wrapperStyle={{ fontSize: 12, color: "#8aa0b2" }} />
                    <Bar dataKey="records" name="Intel records" fill="#2ee6c7" radius={[3, 3, 0, 0]} />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            ) : (
              <EmptyState
                title="No volume to chart yet"
                detail={
                  lastRun
                    ? `Collector last ran ${formatRelative(lastRun.started_at)}, but no dated intel is in this window.`
                    : "The collector has not published chartable records yet."
                }
              />
            )}
          </DataState>
        </Panel>
        <Panel title="Source mix">
          <DataState loading={sources.loading} error={sources.error} retry={sources.reload} code={sources.errorCode}>
            {(sources.data?.data ?? []).length ? (
              <ul className="space-y-3 text-sm">
                {(sources.data?.data ?? []).map((source) => (
                  <li key={source.source_class}>
                    <div className="flex items-center justify-between gap-3">
                      <span className="capitalize">{sourceLabel(source.source_class)}</span>
                      <span className="font-mono text-muted">{source.record_count}</span>
                    </div>
                    <p className="text-xs text-muted">
                      Avg severity {Math.round(source.avg_severity)}
                      {source.last_seen ? ` · last ${formatRelative(source.last_seen)}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No ranked sources" detail="Enable public collectors to populate this list." />
            )}
          </DataState>
        </Panel>
        <Panel title="Latest intelligence" className="xl:col-span-2">
          <DataState loading={intel.loading} error={intel.error} retry={intel.reload} code={intel.errorCode}>
            {records.length ? (
              <ul className="divide-y divide-border/80">
                {records.map((record) => (
                  <li key={record.intel_id}>
                    <Link
                      to={`/intel?intel_id=${encodeURIComponent(record.intel_id)}`}
                      className="flex items-start justify-between gap-3 rounded-lg px-2 py-3 hover:bg-raised"
                    >
                      <span className="min-w-0">
                        <span className="mb-1 flex flex-wrap items-center gap-2">
                          <SeverityBadge band={record.severity_band} />
                          <SourceBadge source={record.source_class || "unknown"} compact />
                        </span>
                        <span className="block truncate text-sm text-ink">
                          {record.products.join(", ") || titleCase(record.intent_label || "Unspecified indicator")}
                        </span>
                        <span className="text-xs text-muted">
                          {record.neighborhood ? titleCase(record.neighborhood) : "Location pending"}
                        </span>
                      </span>
                      <span className="shrink-0 font-mono text-xs text-muted">{formatDate(record.captured_at)}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No intelligence yet" detail="The processor has not written live records." />
            )}
          </DataState>
        </Panel>
        <Panel title="Review queue">
          {reviewRecords.length ? (
            <ul className="space-y-3 text-sm">
              {reviewRecords.map((record) => (
                <li key={record.intel_id} className="flex items-center justify-between gap-3">
                  <Link className="min-w-0 text-teal hover:underline" to={`/intel?intel_id=${encodeURIComponent(record.intel_id)}`}>
                    <span className="block truncate">
                      {record.products.join(", ") || record.neighborhood || titleCase(record.intent_label || "Review")}
                    </span>
                    <span className="text-xs text-muted">
                      {record.neighborhood ? titleCase(record.neighborhood) : "Unlocated"} · {formatRelative(record.captured_at)}
                    </span>
                  </Link>
                  <SeverityBadge band={record.severity_band} />
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Nothing in review" detail="High-severity records will appear here." />
          )}
        </Panel>
      </div>
      <section className="mt-6">
        <h2 className="mb-2 text-sm font-semibold text-ink">Active neighbourhoods</h2>
        <p className="mb-3 text-xs text-muted">Open the intelligence desk filtered to a gazetteer place.</p>
        <div className="flex flex-wrap gap-2">
          {(geo.data?.data ?? []).length ? (
            (geo.data?.data ?? []).slice(0, 16).map((entry) => (
              <Link
                key={entry.neighborhood}
                to={`/intel?neighborhood=${encodeURIComponent(entry.neighborhood)}`}
                className="rounded-full border border-border px-3 py-1 text-xs text-navy hover:border-teal/40"
              >
                {titleCase(entry.neighborhood)} · {entry.count}
              </Link>
            ))
          ) : (
            <span className="text-sm text-muted">No geo-tagged neighbourhoods yet.</span>
          )}
        </div>
      </section>
    </div>
  );
}

function formatChartDate(value: string): string {
  const date = new Date(`${value}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value.slice(5) || value;
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short" }).format(date);
}

function Metric({
  icon,
  label,
  value,
  detail,
}: {
  icon: ReactNode;
  label: string;
  value: string | number;
  detail: string;
}) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-2 flex items-center gap-2 text-muted">
        {icon}
        <span className="text-xs tracking-wider uppercase">{label}</span>
      </div>
      <div className="text-2xl font-semibold">{value}</div>
      <p className="mt-1 text-xs text-muted">{detail}</p>
    </div>
  );
}
