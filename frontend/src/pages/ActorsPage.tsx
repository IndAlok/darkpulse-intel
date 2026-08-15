import { Link } from "react-router-dom";
import { DataState, DataTable, EmptyState, PageHeader } from "../components/Ui";
import { actorsApi } from "../lib/api";
import { formatDate } from "../lib/formatters";
import { useApi } from "../hooks";

export default function ActorsPage() {
  const actors = useApi(() => actorsApi.list());
  const rows = actors.data?.data ?? [];
  return (
    <div>
      <PageHeader
        eyebrow="INVESTIGATE"
        title="Actors"
        description="Vendor aliases aggregated from live intelligence. Graph links use stable vendor IDs."
      />
      <DataState loading={actors.loading} error={actors.error} retry={actors.reload} code={actors.errorCode}>
        {rows.length ? (
          <DataTable columns={["Alias", "Platform", "Listings", "Products", "Places", "Last seen"]}>
            {rows.map((actor) => (
              <tr key={actor.actor_id} className="hover:bg-raised">
                <td className="px-3 py-2">
                  <Link className="text-teal hover:underline" to={`/actors/${encodeURIComponent(actor.actor_id)}`}>
                    {actor.alias}
                  </Link>
                </td>
                <td className="px-3 py-2">{actor.platform || "—"}</td>
                <td className="px-3 py-2 font-mono">{actor.listing_count}</td>
                <td className="px-3 py-2">{(actor.products || []).join(", ") || "—"}</td>
                <td className="px-3 py-2">{(actor.neighborhoods || []).join(", ") || "—"}</td>
                <td className="px-3 py-2 text-xs text-muted">{formatDate(actor.last_seen)}</td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState title="No actors yet" detail="Vendor aliases appear after the processor writes intel." />
        )}
      </DataState>
    </div>
  );
}
