import { useState } from "react";
import {
  ConfirmationDialog,
  DataState,
  DataTable,
  EmptyState,
  PageHeader,
  Toast,
} from "../components/Ui";
import { watchlistApi } from "../lib/api";
import { useApi } from "../hooks";

export default function WatchlistsPage() {
  const lists = useApi(() => watchlistApi.list());
  const [name, setName] = useState("");
  const [terms, setTerms] = useState("");
  const [toast, setToast] = useState<string | null>(null);
  const [removeId, setRemoveId] = useState<string | null>(null);

  return (
    <div>
      <PageHeader
        eyebrow="MONITOR"
        title="Watchlists"
        description="Match counts come from alert history keyed by watchlist ID."
      />
      <form
        className="mb-4 flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void watchlistApi
            .create({
              name,
              terms: terms.split(",").map((item) => item.trim()).filter(Boolean),
              notify: true,
            })
            .then(() => {
              setName("");
              setTerms("");
              return lists.reload();
            })
            .catch((error: Error) => setToast(error.message));
        }}
      >
        <input
          className="rounded border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Name"
          value={name}
          onChange={(event) => setName(event.target.value)}
          required
        />
        <input
          className="min-w-64 flex-1 rounded border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Terms, comma separated"
          value={terms}
          onChange={(event) => setTerms(event.target.value)}
          required
        />
        <button className="rounded bg-teal px-3 py-2 text-sm text-bg">Create</button>
      </form>
      <DataState loading={lists.loading} error={lists.error} retry={lists.reload} code={lists.errorCode}>
        {(lists.data?.data ?? []).length ? (
          <DataTable columns={["Name", "Terms", "Matches", ""]}>
            {(lists.data?.data ?? []).map((list) => (
              <tr key={list.id}>
                <td className="px-3 py-2">{list.name}</td>
                <td className="px-3 py-2 text-sm text-muted">{list.terms.join(", ")}</td>
                <td className="px-3 py-2 font-mono">{list.match_count ?? 0}</td>
                <td className="px-3 py-2">
                  <button className="text-xs text-red-300" onClick={() => setRemoveId(list.id)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState title="No watchlists" detail="Create a term list to generate match counts." />
        )}
      </DataState>
      <ConfirmationDialog
        open={Boolean(removeId)}
        title="Delete watchlist"
        detail="This removes the list. Historical alerts stay."
        destructive
        onClose={() => setRemoveId(null)}
        onConfirm={() => {
          if (!removeId) return;
          void watchlistApi
            .remove(removeId)
            .then(() => lists.reload())
            .catch((error: Error) => setToast(error.message));
          setRemoveId(null);
        }}
      />
      {toast && <Toast message={toast} tone="error" onDismiss={() => setToast(null)} />}
    </div>
  );
}
