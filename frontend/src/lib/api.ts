import type {
  ApiEnvelope,
  IntelSummary,
  IntelRecord,
  IntelEvidence,
  ActorProfile,
  GraphData,
  TrendPoint,
  SourceRanking,
  GeoHeatmapEntry,
  AlertRule,
  AlertHistory,
  SlangEntry,
  Watchlist,
  EvidenceSeal,
  ExportDownload,
  ExportFormat,
  OperationsSource,
  OnionReviewStatus,
  AuditEvent,
  Principal,
  CollectionRun,
  DetailedHealthStatus,
} from "../types/api";
import { getAccessToken, notifyUnauthenticated } from "./auth";

interface RuntimeConfig {
  apiBase?: string;
}

declare global {
  interface Window {
    __DARKPULSE_CONFIG__?: RuntimeConfig;
  }
}

const runtimeConfig: RuntimeConfig =
  typeof window !== "undefined" ? window.__DARKPULSE_CONFIG__ ?? {} : {};

const API_BASE = runtimeConfig.apiBase || import.meta.env.VITE_API_URL || "/api/v1";

export class ApiRequestError extends Error {
  status: number;
  code: string;

  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = "ApiRequestError";
    this.status = status;
    this.code = code;
  }
}

function authHeaders(): Record<string, string> {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function codeForStatus(status: number, fallback = "http_error"): string {
  if (status === 401) return "unauthenticated";
  if (status === 403) return "forbidden";
  if (status === 404) return "not_found";
  if (status === 422) return "request_validation_failed";
  if (status === 429) return "rate_limited";
  if (status >= 500) return "upstream_down";
  return fallback;
}

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...options?.headers,
      },
    });
  } catch {
    throw new ApiRequestError("Unable to reach the API", 0, "upstream_down");
  }

  if (!response.ok) {
    const body = await response.text();
    let parsed: { errors?: Array<{ message?: string; code?: string }> } | null = null;
    try {
      parsed = JSON.parse(body) as { errors?: Array<{ message?: string; code?: string }> };
    } catch {
      parsed = null;
    }
    const code = parsed?.errors?.[0]?.code || codeForStatus(response.status);
    if (response.status === 401) {
      notifyUnauthenticated();
    }
    throw new ApiRequestError(
      parsed?.errors?.[0]?.message || `API Error: ${response.status} ${response.statusText}`,
      response.status,
      code,
    );
  }

  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const authApi = {
  login: (token: string) =>
    apiFetch<ApiEnvelope<Principal & { token: string }>>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),
  me: () => apiFetch<ApiEnvelope<Principal>>("/auth/me"),
};

export const intelApi = {
  list: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return apiFetch<ApiEnvelope<IntelSummary[]>>(`/intel${query}`);
  },
  get: (id: string) => apiFetch<ApiEnvelope<IntelRecord>>(`/intel/${encodeURIComponent(id)}`),
  evidence: (id: string) =>
    apiFetch<ApiEnvelope<IntelEvidence>>(`/intel/${encodeURIComponent(id)}/evidence`),
};

export const actorsApi = {
  list: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return apiFetch<ApiEnvelope<ActorProfile[]>>(`/actors${query}`);
  },
  get: (id: string) => apiFetch<ApiEnvelope<ActorProfile>>(`/actors/${id}`),
};

export const graphApi = {
  get: (center?: string, depth?: number, maxNodes?: number) => {
    const params = new URLSearchParams();
    if (center) params.set("center", center);
    if (depth) params.set("depth", String(depth));
    if (maxNodes) params.set("max_nodes", String(maxNodes));
    return apiFetch<GraphData>(`/graph?${params}`);
  },
};

export const searchApi = {
  search: (q: string, lang?: string, limit = 50) => {
    const params = new URLSearchParams({ q });
    if (lang) params.set("lang", lang);
    params.set("limit", String(limit));
    return apiFetch<ApiEnvelope<IntelRecord[]>>(`/search?${params}`);
  },
};

export const dashboardApi = {
  trends: (period?: string) => {
    const query = period ? `?period=${period}` : "";
    return apiFetch<ApiEnvelope<TrendPoint[]>>(`/dashboards/trends${query}`);
  },
  sources: () => apiFetch<ApiEnvelope<SourceRanking[]>>("/dashboards/sources"),
  geo: () => apiFetch<ApiEnvelope<GeoHeatmapEntry[]>>("/dashboards/geo"),
};

export const watchlistApi = {
  list: () => apiFetch<ApiEnvelope<Watchlist[]>>("/watchlists"),
  create: (payload: Pick<Watchlist, "name" | "terms" | "notify">) =>
    apiFetch<ApiEnvelope<Watchlist>>("/watchlists", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (id: string, payload: Omit<Watchlist, "id" | "created_at" | "updated_at" | "match_count">) =>
    apiFetch<ApiEnvelope<Watchlist>>(`/watchlists/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  remove: (id: string) => apiFetch<void>(`/watchlists/${id}`, { method: "DELETE" }),
};

export const slangApi = {
  list: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return apiFetch<ApiEnvelope<SlangEntry[]>>(`/slang${query}`);
  },
  candidates: (limit = 50) =>
    apiFetch<ApiEnvelope<SlangEntry[]>>(`/slang/candidates?limit=${limit}`),
  create: (
    payload: Pick<SlangEntry, "term" | "meaning" | "lang" | "confidence" | "newly_discovered">,
  ) =>
    apiFetch<ApiEnvelope<SlangEntry>>("/slang", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  update: (
    id: string,
    payload: Omit<SlangEntry, "id" | "created_at" | "updated_at" | "usage_count">,
  ) =>
    apiFetch<ApiEnvelope<SlangEntry>>(`/slang/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),
  approve: (id: string) =>
    apiFetch<ApiEnvelope<SlangEntry>>(`/slang/${id}/approve`, { method: "POST" }),
  reject: (id: string) =>
    apiFetch<ApiEnvelope<SlangEntry>>(`/slang/${id}/reject`, { method: "POST" }),
  remove: (id: string) => apiFetch<void>(`/slang/${id}`, { method: "DELETE" }),
};

export const alertsApi = {
  config: () => apiFetch<ApiEnvelope<{ rules: AlertRule[] }>>("/alerts/config"),
  updateConfig: (rules: AlertRule[]) =>
    apiFetch<ApiEnvelope<{ rules: AlertRule[] }>>("/alerts/config", {
      method: "PUT",
      body: JSON.stringify({ rules }),
    }),
  history: (params?: Record<string, string>) => {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    return apiFetch<ApiEnvelope<AlertHistory[]>>(`/alerts/history${query}`);
  },
  patch: (id: string, payload: { acknowledged?: boolean; assignee?: string; resolved?: boolean }) =>
    apiFetch<ApiEnvelope<AlertHistory>>(`/alerts/history/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    }),
};

export const exportApi = {
  report: async (format: ExportFormat, intelIds: string[] = []): Promise<ExportDownload> => {
    const query = new URLSearchParams({ format });
    intelIds.forEach((id) => query.append("intel_ids", id));
    let response: Response;
    try {
      response = await fetch(`${API_BASE}/export?${query}`, {
        headers: authHeaders(),
      });
    } catch {
      throw new ApiRequestError("Unable to reach the API", 0, "upstream_down");
    }
    if (!response.ok) {
      if (response.status === 401) notifyUnauthenticated();
      throw new ApiRequestError(
        `Export failed: ${response.status} ${response.statusText}`,
        response.status,
        codeForStatus(response.status),
      );
    }
    const disposition = response.headers.get("Content-Disposition") || "";
    const match = disposition.match(/filename="?([^"]+)"?/);
    const filename = match ? match[1] : "darkpulse-export";
    return {
      filename,
      blob: await response.blob(),
      contentType: response.headers.get("Content-Type") || "application/octet-stream",
      evidenceSeal: response.headers.get("X-DarkPulse-Evidence-Seal") || undefined,
    };
  },
};

export const evidenceApi = {
  seal: (payload: string) =>
    apiFetch<ApiEnvelope<EvidenceSeal>>("/evidence/seal", {
      method: "POST",
      body: JSON.stringify({ payload }),
    }),
  get: (hash: string) => apiFetch<ApiEnvelope<EvidenceSeal>>(`/evidence/${hash}`),
  verifyPayload: (payload: string, hash: string) =>
    apiFetch<
      ApiEnvelope<{ matches: boolean; payload_hash: string; ledger_recorded: boolean }>
    >("/evidence/verify", {
      method: "POST",
      body: JSON.stringify({ payload, hash_sha256: hash }),
    }),
  verifyChain: () =>
    apiFetch<
      ApiEnvelope<{
        verified: boolean;
        record_count: number;
        breaks: Array<Record<string, unknown>>;
      }>
    >("/evidence/verify"),
};

export const healthApi = {
  check: () =>
    apiFetch<{ status: string; service?: string; version?: string }>("/health"),
  detailed: () => apiFetch<DetailedHealthStatus>("/health"),
};

export const operationsApi = {
  sources: () => apiFetch<ApiEnvelope<OperationsSource[]>>("/operations/sources"),
  processing: () => apiFetch<ApiEnvelope<Record<string, number>>>("/operations/processing"),
  onionReview: () => apiFetch<ApiEnvelope<OnionReviewStatus>>("/operations/onion-review"),
  audit: (limit = 50) =>
    apiFetch<ApiEnvelope<AuditEvent[]>>(`/operations/audit?limit=${limit}`),
  collectionRuns: (limit = 50) =>
    apiFetch<ApiEnvelope<CollectionRun[]>>(`/operations/collection-runs?limit=${limit}`),
};

export const wsUrl = () => {
  const token = getAccessToken();
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  const query = token ? `?access_token=${encodeURIComponent(token)}` : "";
  return `${proto}//${window.location.host}/api/v1/alerts/ws${query}`;
};
