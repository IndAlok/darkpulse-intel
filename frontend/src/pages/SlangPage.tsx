import { useState } from "react";
import { usePrincipal } from "../lib/principal";
import { DataState, DataTable, EmptyState, PageHeader, Toast } from "../components/Ui";
import { slangApi } from "../lib/api";
import { useApi } from "../hooks";

const LANGS = ["en", "hi", "gu", "hinglish", "emoji"];

export default function SlangPage() {
  const dictionary = useApi(() => slangApi.list());
  const candidates = useApi(() => slangApi.candidates());
  const canWrite = usePrincipal()?.role !== "viewer";
  const [toast, setToast] = useState<string | null>(null);
  const [term, setTerm] = useState("");
  const [meaning, setMeaning] = useState("");
  const [lang, setLang] = useState("en");
  const [busy, setBusy] = useState<string | null>(null);

  const review = async (id: string, action: "approve" | "reject") => {
    setBusy(id);
    try {
      await (action === "approve" ? slangApi.approve(id) : slangApi.reject(id));
      await Promise.all([candidates.reload(), dictionary.reload()]);
    } catch (error) {
      setToast(error instanceof Error ? error.message : "Review failed");
    } finally {
      setBusy(null);
    }
  };

  return (
    <div>
      <PageHeader
        eyebrow="MONITOR"
        title="Slang review"
        description="Usage counts come from decoded intel. Automatic slang discovery is off until a slang embedding model is configured, so analysts add terms here."
      />
      {canWrite && (
        <form
          className="mb-4 flex flex-wrap gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            void slangApi
              .create({ term, meaning, lang, confidence: 1, newly_discovered: false })
              .then(() => {
                setTerm("");
                setMeaning("");
                return dictionary.reload();
              })
              .catch((error: Error) => setToast(error.message));
          }}
        >
          <input
            aria-label="Term"
            className="rounded border border-border bg-surface px-3 py-2 text-sm"
            placeholder="Term"
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            required
          />
          <input
            aria-label="Meaning"
            className="min-w-64 flex-1 rounded border border-border bg-surface px-3 py-2 text-sm"
            placeholder="Meaning"
            value={meaning}
            onChange={(event) => setMeaning(event.target.value)}
            required
          />
          <select
            aria-label="Language"
            className="rounded border border-border bg-surface px-3 py-2 text-sm"
            value={lang}
            onChange={(event) => setLang(event.target.value)}
          >
            {LANGS.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </select>
          <button className="rounded bg-teal px-3 py-2 text-sm text-bg">Add approved term</button>
        </form>
      )}
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
                  {canWrite && (
                    <>
                      <button
                        className="mr-2 text-xs text-teal disabled:opacity-40"
                        disabled={busy === entry.id}
                        onClick={() => void review(entry.id, "approve")}
                      >
                        Approve
                      </button>
                      <button
                        className="text-xs text-red-300 disabled:opacity-40"
                        disabled={busy === entry.id}
                        onClick={() => void review(entry.id, "reject")}
                      >
                        Reject
                      </button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </DataTable>
        ) : (
          <EmptyState title="No pending candidates" detail="Discovery is off, so the queue stays empty." />
        )}
      </DataState>
      <h2 className="mt-6 mb-2 text-sm font-semibold">
        Dictionary{" "}
        <span className="font-normal text-muted">
          (latest {(dictionary.data?.data ?? []).length} of 500 by review date)
        </span>
      </h2>
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
