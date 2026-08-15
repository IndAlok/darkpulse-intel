import { BadgeCheck, Clock3, Fingerprint, Link2 } from "lucide-react";
import { formatDate } from "../lib/formatters";
import type { EvidenceSeal } from "../types/api";
import { Panel } from "./Ui";

export function EvidenceSealCard({
  seal,
  title = "Evidence seal",
}: {
  seal: EvidenceSeal;
  title?: string;
}) {
  return (
    <Panel title={title}>
      <div className="grid gap-3 text-sm md:grid-cols-2">
        <div>
          <Fingerprint size={16} className="mb-1 text-teal" />
          <span className="block text-xs text-muted">SHA-256</span>
          <code className="break-all font-mono text-xs">{seal.hash_sha256}</code>
        </div>
        <div>
          <Clock3 size={16} className="mb-1 text-navy" />
          <span className="block text-xs text-muted">Sealed</span>
          <strong>{formatDate(new Date(seal.sealed_at * 1000).toISOString())}</strong>
        </div>
        <div>
          <BadgeCheck size={16} className="mb-1 text-teal" />
          <span className="block text-xs text-muted">TSA status</span>
          <strong>{seal.tsa_verified ? "Verified" : "Not externally verified"}</strong>
        </div>
        <div>
          <Link2 size={16} className="mb-1 text-muted" />
          <span className="block text-xs text-muted">Chain predecessor</span>
          <code className="break-all font-mono text-xs">{seal.previous_hash || "Genesis seal"}</code>
        </div>
      </div>
    </Panel>
  );
}
