export interface Pagination {
  cursor: string | null;
  limit: number;
  total: number;
}

export interface ApiError {
  code: string;
  message: string;
  trace_id?: string;
}

export interface ApiEnvelope<T> {
  data: T;
  pagination?: Pagination;
  meta?: Record<string, unknown>;
  errors?: ApiError[];
}

export type SourceClass =
  | "dnm_dataset"
  | "tor_market"
  | "tor_forum"
  | "telegram"
  | "surface_market"
  | "social"
  | "paste"
  | "i2p";
export type ContactType =
  | "telegram"
  | "wickr"
  | "signal"
  | "email"
  | "phone_redacted"
  | "pgp";
export type SlangReviewStatus = "pending" | "approved" | "rejected";

export type SeverityBand = "info" | "low" | "medium" | "high" | "critical";
export type IntentLabel =
  | "sale"
  | "solicitation"
  | "discussion"
  | "review"
  | "unrelated";
export type GeoBasis = "explicit" | "slang" | "ship_from" | "inference";

export interface IntelRecord {
  intel_id: string;
  ingest_id: string;
  trace_id?: string;
  source_class?: SourceClass;
  captured_at: string;
  content_hash?: string;
  language?: { detected: string[]; code_mixed: boolean; romanized: boolean };
  sanitization: {
    status: "clean" | "sanitized" | "dropped";
    detectors_fired: string[];
    illegal_flag: boolean;
  };
  translated_text?: string;
  intent: {
    label: IntentLabel;
    score: number;
  };
  products: Product[];
  slang_decoded: SlangMatch[];
  geo?: GeoLocation;
  entities?: IntelEntities;
  actor_links: ActorLink[];
  severity: Severity;
  confidence: number;
  tags: string[];
  evidence_ref?: string;
  evidence_snapshot?: EvidenceSnapshot;
}

export interface Product {
  canonical?: string;
  raw_term?: string;
  slang?: boolean;
  quantity?: string;
  price?: string;
}

export interface SlangMatch {
  term: string;
  meaning?: string;
  lang?: string;
  confidence: number;
  newly_discovered: boolean;
}

export interface GeoLocation {
  neighborhood?: string;
  city?: string;
  confidence: number;
  basis?: GeoBasis;
}

export interface Severity {
  score: number;
  band: SeverityBand;
  factors?: Record<string, unknown>;
}

export interface IntelEntities {
  vendors: Array<{ alias?: string; platform?: string }>;
  buyers: Record<string, unknown>[];
  crypto_wallets: Array<{ chain?: string; address?: string }>;
  contacts: Array<{ type: ContactType; value_redacted?: string }>;
  pgp_fingerprints: string[];
}

export interface ActorLink {
  from: string;
  to: string;
  relation: string;
  confidence: number;
}

export interface EvidenceSnapshot {
  source_ref?: string;
  captured_at?: string;
  source_sha256?: string;
  content_sha256?: string;
  collector_id?: string;
  collector_version?: string;
  excerpt?: string;
}

export interface IntelEvidence {
  intel_id: string;
  trace_id?: string;
  source_ref?: string;
  captured_at?: string;
  source_sha256?: string;
  content_sha256?: string;
  excerpt: string;
}

export interface IntelSummary {
  intel_id: string;
  ingest_id: string;
  source_class?: string;
  captured_at: string;
  intent_label: string;
  intent_score: number;
  severity_score: number;
  severity_band: string;
  products: string[];
  neighborhood: string;
  vendor_aliases: string[];
  confidence: number;
  tags: string[];
}

export interface ActorProfile {
  actor_id: string;
  alias: string;
  platform: string;
  listing_count: number;
  first_seen?: string;
  last_seen?: string;
  avg_severity: number;
  products: string[];
  neighborhoods: string[];
  timeline?: Array<{
    intel_id: string;
    captured_at: string;
    intent?: string;
    severity?: string;
  }>;
}

export type GraphNodeType =
  | "Vendor"
  | "Wallet"
  | "Product"
  | "Neighborhood"
  | "Market"
  | "IntelRef";

export interface GraphNode {
  id: string;
  label: string;
  type: GraphNodeType;
  properties?: Record<string, unknown>;
}

export interface GraphEdge {
  source: string;
  target: string;
  relation: string;
  confidence: number;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  truncated: boolean;
  limits: Record<string, number>;
}

export interface TrendPoint {
  date: string;
  count: number;
  products: Record<string, number>;
}

export interface SourceRanking {
  source_class: string;
  record_count: number;
  avg_severity: number;
  last_seen?: string;
}

export interface GeoHeatmapEntry {
  neighborhood: string;
  count: number;
  avg_severity: number;
  top_products: string[];
}

export interface AlertRule {
  name: string;
  severity_min: number;
  products: string[];
  neighborhoods: string[];
  enabled: boolean;
}

export interface AlertConfig {
  rules: AlertRule[];
}

export interface AlertHistory {
  id: string;
  rule_name: string;
  intel_id: string;
  triggered_at: string;
  severity_score: number;
  context?: string;
  acknowledged?: boolean;
  assignee?: string | null;
  resolved_at?: string | null;
  watchlist_id?: string;
}

export interface SlangEntry {
  id: string;
  term: string;
  meaning: string;
  lang?: string;
  confidence: number;
  newly_discovered: boolean;
  review_status: SlangReviewStatus;
  created_at?: string;
  updated_at?: string;
  usage_count?: number;
}

export interface EvidenceSeal {
  hash_sha256: string;
  tsa_token: string;
  tsa_verified: boolean;
  sealed_at: number;
  provenance: string;
  previous_hash?: string | null;
}

export type ExportFormat = "csv" | "json" | "pdf";

export interface ExportDownload {
  filename: string;
  blob: Blob;
  contentType: string;
  evidenceSeal?: string;
}

export interface Watchlist {
  id: string;
  name: string;
  terms: string[];
  notify: boolean;
  enabled: boolean;
  created_at?: string;
  updated_at?: string;
  match_count?: number;
}

export interface Principal {
  subject: string;
  role: "viewer" | "analyst" | "administrator";
}

export interface CollectionRun {
  source_id: string;
  started_at?: string;
  finished_at?: string;
  published?: number;
  duplicates?: number;
  rejected?: number;
  failures?: number;
  failure_code?: string | null;
  skipped?: boolean;
}

export interface OperationsSource {
  source_id: string;
  source_class: string;
  enabled: boolean;
  max_retries: number;
}

export interface OnionReviewStatus {
  reviewed_source_count: number;
  approved_enabled_count: number;
  disabled_count: number;
  policy: string;
}

export interface AuditEvent {
  occurred_at: string;
  actor: string;
  role: string;
  action: string;
  target_type?: string;
  target_id?: string;
  metadata?: Record<string, unknown>;
}

export interface HealthStatus {
  status: string;
  service?: string;
  version?: string;
}

export interface DetailedHealthStatus {
  status: string;
  services?: Record<
    string,
    {
      status?: string;
      latency_ms?: number;
      last_started_at?: string;
      source_id?: string;
    }
  >;
}
