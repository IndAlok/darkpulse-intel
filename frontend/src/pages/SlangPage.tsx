import { useState } from "react";
import { DataState, DataTable, EmptyState, PageHeader, Toast } from "../components/Ui";
import { slangApi } from "../lib/api";
import { useApi } from "../hooks";

export default function SlangPage() {
  const dictionary = useApi(() => slangApi.list());
  const candidates = useApi(() => slangApi.candidates());
  const [toast, setToast] = useState<string | null>(null);
  const [term, setTerm] = useState("");
  const [meaning, setMeaning] = useState("");

  return (
    <div>
      <PageHeader
        eyebrow="MONITOR"
        title="Slang review"
        description="Usage counts come from decoded intel. Candidates persist when auto-discovery is enabled."
      />
      <form
        className="mb-4 flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          void slangApi
            .create({ term, meaning, lang: "en", confidence: 1, newly_discovered: false })
            .then(() => {
              setTerm("");
              setMeaning("");
              return dictionary.reload();
            })
            .catch((error: Error) => setToast(error.message));
        }}
      >
        <input
          className="rounded border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Term"
          value={term}
          onChange={(event) => setTerm(event.target.value)}
          required
        />
        <input
          className="min-w-64 flex-1 rounded border border-border bg-surface px-3 py-2 text-sm"
          placeholder="Meaning"
          value={meaning}
          onChange={(event) => setMeaning(event.target.value)}
          required
        />
        <button className="rounded bg-teal px-3 py-2 text-sm text-bg">Add approved term</button>
      </form>
      <h2 className="mb-2 text-sm font-semibold">Review queue</h2>
      <DataState
        loading={candidates.loading}
        error={candidates.error}
        retry={candidates.reload}
        code={candidates.errorCode}
      >
        {(candidates.data?.data ?? []).length ? (
          <DataTable columns={["Term", "Meaning", "Usage", ""]}>
            {(candidates.data?.data ?? []).map((entry) => (
              <tr key={entry.id}>
                <td className="px-3 py-2 font-mono">{entry.term}</td>
                <td className="px-3 py-2">{entry.meaning}</td>
                <td className="px-3 py-2">{entry.usage_count ?? 0}</td>
                <td className="px-3 py-2">
                  <button
                    className="mr-2 text-xs text-teal"
                    onClick={() =>
                      void slangApi.approve(entry.id).then(() => {
                        void candidates.reload();
                        void dictionary.reload();
                      })
                    }
                  >
                    Approve
                  </button>
                  <button
                    className="text-xs text-red-300"
                    onClick={() => void slangApi.reject(entry.id).then(() => candidates.reload())}
                  >
                    Reject
                  </button>
                </td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState title="No pending candidates" detail="Auto-discovery writes pending terms into Mongo." />
        )}
      </DataState>
      <h2 className="mt-6 mb-2 text-sm font-semibold">Dictionary</h2>
      <DataState
        loading={dictionary.loading}
        error={dictionary.error}
        retry={dictionary.reload}
        code={dictionary.errorCode}
      >
        {(dictionary.data?.data ?? []).length ? (
          <DataTable columns={["Term", "Meaning", "Lang", "Status", "Usage"]}>
            {(dictionary.data?.data ?? []).map((entry) => (
              <tr key={entry.id}>
                <td className="px-3 py-2 font-mono">{entry.term}</td>
                <td className="px-3 py-2">{entry.meaning}</td>
                <td className="px-3 py-2">{entry.lang}</td>
                <td className="px-3 py-2">{entry.review_status}</td>
                <td className="px-3 py-2">{entry.usage_count ?? 0}</td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState title="Dictionary empty" />
        )}
      </DataState>
      {toast && <Toast message={toast} tone="error" onDismiss={() => setToast(null)} />}
    </div>
  );
}
