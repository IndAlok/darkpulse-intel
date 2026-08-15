import { FileSearch, LockKeyhole, SearchCheck, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { EvidenceSealCard } from "../components/EvidenceSealCard";
import { DataState, EmptyState, PageHeader, Panel, Toast } from "../components/Ui";
import { evidenceApi, intelApi } from "../lib/api";
import { useApi } from "../hooks";
import type { EvidenceSeal } from "../types/api";

export default function EvidencePage() {
  const [payload, setPayload] = useState("");
  const [seal, setSeal] = useState<EvidenceSeal | null>(null);
  const [lookupHash, setLookupHash] = useState("");
  const [lookupSeal, setLookupSeal] = useState<EvidenceSeal | null>(null);
  const [verifyPayload, setVerifyPayload] = useState("");
  const [verifyHash, setVerifyHash] = useState("");
  const [verification, setVerification] = useState<{
    matches: boolean;
    payload_hash: string;
    ledger_recorded: boolean;
  } | null>(null);
  const [intelId, setIntelId] = useState("");
  const [requestedIntel, setRequestedIntel] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const linkedEvidence = useApi(
    () => (requestedIntel ? intelApi.evidence(requestedIntel) : Promise.resolve(null)),
    requestedIntel,
  );
  const chain = useApi(() => evidenceApi.verifyChain());

  return (
    <div>
      <PageHeader
        eyebrow="EVIDENCE"
        title="Evidence workspace"
        description="Seal permitted payloads, inspect ledger entries, and verify hashes. Not a claim of legal admissibility."
      />
      <div className="grid gap-4 lg:grid-cols-2">
        <Panel title="Seal permitted text">
          <textarea
            className="mb-3 h-28 w-full rounded border border-border bg-bg p-2 text-sm"
            value={payload}
            onChange={(event) => setPayload(event.target.value)}
            placeholder="Case note or approved evidence manifest text."
          />
          <button
            className="inline-flex items-center gap-2 rounded bg-teal px-3 py-1.5 text-sm text-bg"
            onClick={() => {
              if (!payload.trim()) return setMessage("Enter a permitted text payload to seal.");
              void evidenceApi
                .seal(payload)
                .then((response) => {
                  setSeal(response.data);
                  setMessage("Payload sealed and recorded in the evidence ledger.");
                })
                .catch((error: Error) => setMessage(error.message));
            }}
          >
            <LockKeyhole size={15} /> Seal payload
          </button>
        </Panel>
        <Panel title="Verify a payload">
          <textarea
            className="mb-2 h-20 w-full rounded border border-border bg-bg p-2 text-sm"
            value={verifyPayload}
            onChange={(event) => setVerifyPayload(event.target.value)}
          />
          <input
            className="mb-3 w-full rounded border border-border bg-bg px-3 py-2 font-mono text-sm"
            value={verifyHash}
            onChange={(event) => setVerifyHash(event.target.value)}
            placeholder="64-character SHA-256"
          />
          <button
            className="inline-flex items-center gap-2 rounded border border-border px-3 py-1.5 text-sm"
            onClick={() => {
              if (!verifyPayload.trim() || !verifyHash.trim()) {
                setMessage("Enter both the payload text and its claimed seal hash.");
                return;
              }
              void evidenceApi
                .verifyPayload(verifyPayload, verifyHash.trim())
                .then((response) => setVerification(response.data))
                .catch((error: Error) => setMessage(error.message));
            }}
          >
            <ShieldCheck size={15} /> Verify against seal
          </button>
          {verification && (
            <p className="mt-3 text-sm">
              {verification.matches ? "Payload matches the seal hash." : "Payload does not match."}{" "}
              {verification.ledger_recorded ? "Recorded in the ledger." : "Not in the ledger."}
            </p>
          )}
        </Panel>
        <Panel title="Inspect a seal">
          <div className="flex gap-2">
            <input
              className="flex-1 rounded border border-border bg-bg px-3 py-2 font-mono text-sm"
              value={lookupHash}
              onChange={(event) => setLookupHash(event.target.value)}
            />
            <button
              className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-sm"
              onClick={() => {
                if (!lookupHash.trim()) return setMessage("Enter an evidence seal hash.");
                void evidenceApi
                  .get(lookupHash.trim())
                  .then((response) => setLookupSeal(response.data))
                  .catch((error: Error) => setMessage(error.message));
              }}
            >
              <SearchCheck size={15} /> Inspect
            </button>
          </div>
        </Panel>
        <Panel title="Chain verification">
          <DataState loading={chain.loading} error={chain.error} retry={chain.reload} code={chain.errorCode}>
            {chain.data?.data ? (
              <p className="text-sm">
                {chain.data.data.verified ? "Seal chain intact" : "Seal chain broken"} ·{" "}
                {chain.data.data.record_count} records · {chain.data.data.breaks.length} breaks
              </p>
            ) : (
              <EmptyState title="No seals recorded" />
            )}
          </DataState>
        </Panel>
      </div>
      <Panel title="Record-linked evidence" className="mt-4">
        <div className="mb-3 flex gap-2">
          <input
            className="flex-1 rounded border border-border bg-bg px-3 py-2 text-sm"
            value={intelId}
            onChange={(event) => setIntelId(event.target.value)}
            placeholder="Intelligence ID"
          />
          <button
            className="inline-flex items-center gap-1 rounded border border-border px-3 py-1.5 text-sm"
            onClick={() => setRequestedIntel(intelId.trim())}
          >
            <FileSearch size={15} /> Inspect record
          </button>
        </div>
        <DataState
          loading={linkedEvidence.loading}
          error={linkedEvidence.error}
          retry={linkedEvidence.reload}
          code={linkedEvidence.errorCode}
        >
          {linkedEvidence.data?.data ? (
            <div className="space-y-1 text-sm">
              <strong>{linkedEvidence.data.data.intel_id}</strong>
              <p className="text-muted">{linkedEvidence.data.data.excerpt}</p>
            </div>
          ) : requestedIntel ? (
            <EmptyState title="No record-linked evidence" />
          ) : (
            <p className="text-sm text-muted">Enter an intelligence ID to retrieve its excerpt.</p>
          )}
        </DataState>
      </Panel>
      {seal && <div className="mt-4"><EvidenceSealCard title="Newly created seal" seal={seal} /></div>}
      {lookupSeal && <div className="mt-4"><EvidenceSealCard title="Ledger seal" seal={lookupSeal} /></div>}
      {message && <Toast message={message} onDismiss={() => setMessage(null)} />}
    </div>
  );
}
