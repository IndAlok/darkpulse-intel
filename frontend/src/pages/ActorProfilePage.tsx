import { Link, useParams } from "react-router-dom";
import IntelDetailDrawer from "../components/IntelDetailDrawer";
import { DataState, EmptyState, PageHeader, Timeline } from "../components/Ui";
import { actorsApi } from "../lib/api";
import { formatDate } from "../lib/formatters";
import { useApi } from "../hooks";
import { useState } from "react";

export default function ActorProfilePage() {
  const { actorId = "" } = useParams();
  const profile = useApi(() => actorsApi.get(actorId), actorId);
  const actor = profile.data?.data;
  const [intelId, setIntelId] = useState<string | null>(null);
  return (
    <div>
      <PageHeader
        eyebrow="ACTOR"
        title={actor?.alias || actorId}
        description="Flattened products, neighbourhoods, and a timeline into live intelligence."
        action={
          <Link
            to={`/graph?center=vendor:${encodeURIComponent(actor?.alias || actorId)}`}
            className="rounded border border-border px-3 py-1.5 text-sm text-teal"
          >
            Open graph
          </Link>
        }
      />
      <DataState loading={profile.loading} error={profile.error} retry={profile.reload} code={profile.errorCode}>
        {actor ? (
          <div className="grid gap-4 lg:grid-cols-3">
            <section className="rounded-xl border border-border bg-surface p-4 lg:col-span-2">
              <p className="text-sm text-muted">
                {actor.platform || "Unknown platform"} · {actor.listing_count} listings · avg severity{" "}
                {actor.avg_severity}
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {(actor.products || []).map((product) => (
                  <span key={product} className="rounded-full bg-raised px-2 py-1 text-xs">
                    {product}
                  </span>
                ))}
                {(actor.neighborhoods || []).map((place) => (
                  <Link
                    key={place}
                    to={`/intel?neighborhood=${encodeURIComponent(place)}`}
                    className="rounded-full border border-border px-2 py-1 text-xs text-navy"
                  >
                    {place}
                  </Link>
                ))}
              </div>
            </section>
            <section className="rounded-xl border border-border bg-surface p-4">
              <h2 className="mb-3 text-sm font-semibold">Timeline</h2>
              {actor.timeline?.length ? (
                <Timeline
                  items={actor.timeline.map((item) => ({
                    title: item.intent || item.intel_id,
                    detail: item.severity,
                    time: formatDate(item.captured_at),
                  }))}
                />
              ) : (
                <EmptyState title="No timeline" />
              )}
              <ul className="mt-3 space-y-1 text-sm">
                {actor.timeline?.map((item) => (
                  <li key={item.intel_id}>
                    <button className="text-teal hover:underline" onClick={() => setIntelId(item.intel_id)}>
                      {item.intel_id}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          </div>
        ) : (
          <EmptyState title="Actor not found" />
        )}
      </DataState>
      <IntelDetailDrawer intelId={intelId} onClose={() => setIntelId(null)} />
    </div>
  );
}
