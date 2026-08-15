import { AlertTriangle, Database, RefreshCw, X } from "lucide-react";
import { useEffect, useRef, type ReactNode, type RefObject } from "react";
import type { SeverityBand } from "../types/api";

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
      <div>
        <span className="font-mono text-[11px] tracking-[0.22em] text-teal uppercase">
          {eyebrow}
        </span>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">{title}</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted">{description}</p>
      </div>
      {action}
    </header>
  );
}

const BAND_STYLES: Record<string, string> = {
  critical: "bg-red-500/15 text-red-300",
  high: "bg-amber-500/15 text-amber-200",
  medium: "bg-yellow-500/10 text-yellow-100",
  low: "bg-sky-500/10 text-navy",
  info: "bg-white/5 text-muted",
};

export function SeverityBadge({ band }: { band: SeverityBand | string }) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2 py-0.5 text-[11px] font-medium uppercase ${BAND_STYLES[band] || BAND_STYLES.info}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {band}
    </span>
  );
}

export function SourceBadge({
  source,
  compact = false,
}: {
  source: string;
  compact?: boolean;
}) {
  return (
    <span
      className={`inline-flex rounded border border-border bg-raised px-2 py-0.5 font-mono text-[11px] text-navy ${compact ? "" : ""}`}
    >
      {source.replaceAll("_", " ")}
    </span>
  );
}

export function FilterChip({
  children,
  active = false,
  onClick,
}: {
  children: ReactNode;
  active?: boolean;
  onClick?: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`rounded-full border px-3 py-1 text-xs ${
        active
          ? "border-teal/40 bg-teal/10 text-teal"
          : "border-border bg-raised text-muted hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

export function LoadingState() {
  return (
    <div className="flex items-center gap-3 rounded-lg border border-border bg-surface px-4 py-6 text-sm text-muted">
      <RefreshCw className="animate-spin text-teal" size={18} />
      <span>Loading intelligence data…</span>
    </div>
  );
}

export function SkeletonGrid({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="h-10 animate-pulse rounded bg-raised" />
      ))}
    </div>
  );
}

export function EmptyState({
  title = "No records available",
  detail = "The API returned no records for this view.",
}: {
  title?: string;
  detail?: string;
}) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-dashed border-border bg-surface px-4 py-6">
      <Database size={20} className="mt-0.5 text-muted" />
      <div>
        <strong className="block text-sm text-ink">{title}</strong>
        <span className="text-sm text-muted">{detail}</span>
      </div>
    </div>
  );
}

export function errorTitle(error: string, code?: string | null): string {
  switch (code) {
    case "unauthenticated":
      return "Sign in required";
    case "forbidden":
      return "Access denied";
    case "request_validation_failed":
      return "Invalid request";
    case "not_found":
      return "Not found";
    case "rate_limited":
      return "Rate limited";
    case "upstream_down":
    case "internal_error":
      return "Service error";
    default:
      return error.toLowerCase().includes("unable to reach")
        ? "API unavailable"
        : "Request failed";
  }
}

export function ErrorState({
  error,
  retry,
  code,
}: {
  error: string;
  retry: () => void;
  code?: string | null;
}) {
  return (
    <div className="flex items-start gap-3 rounded-lg border border-red-500/30 bg-red-500/5 px-4 py-6">
      <AlertTriangle size={20} className="mt-0.5 text-red-300" />
      <div>
        <strong className="block text-sm text-ink">{errorTitle(error, code)}</strong>
        <span className="block text-sm text-muted">{error}</span>
        <button className="mt-2 text-sm text-teal hover:underline" onClick={retry}>
          Try again
        </button>
      </div>
    </div>
  );
}

export function DataState({
  loading,
  error,
  retry,
  children,
  code,
}: {
  loading: boolean;
  error: string | null;
  retry: () => void;
  children: ReactNode;
  code?: string | null;
}) {
  if (loading) return <LoadingState />;
  if (error) return <ErrorState error={error} retry={retry} code={code} />;
  return <>{children}</>;
}

export function Confidence({ value }: { value: number }) {
  const percent = Math.round(value <= 1 ? value * 100 : value);
  return (
    <span className="inline-flex items-center gap-2 font-mono text-xs text-muted">
      <span className="h-1.5 w-16 overflow-hidden rounded-full bg-raised">
        <span className="block h-full bg-teal" style={{ width: `${Math.min(percent, 100)}%` }} />
      </span>
      {percent}%
    </span>
  );
}

export function Panel({
  title,
  children,
  className = "",
  kicker,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  kicker?: string;
}) {
  return (
    <section className={`rounded-xl border border-border bg-surface p-4 ${className}`}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {kicker ? (
          <span className="font-mono text-[10px] tracking-widest text-muted uppercase">
            {kicker}
          </span>
        ) : null}
      </div>
      {children}
    </section>
  );
}

export function DataTable({
  columns,
  children,
  label = "Data table",
}: {
  columns: string[];
  children: ReactNode;
  label?: string;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[640px] text-left text-sm" aria-label={label}>
        <thead>
          <tr className="border-b border-border text-[11px] tracking-wider text-muted uppercase">
            {columns.map((column) => (
              <th key={column} className="px-3 py-2 font-medium">
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border/80">{children}</tbody>
      </table>
    </div>
  );
}

export function Pagination({
  hasPrevious,
  hasNext,
  onPrevious,
  onNext,
}: {
  hasPrevious: boolean;
  hasNext: boolean;
  onNext: () => void;
  onPrevious: () => void;
}) {
  return (
    <nav className="mt-4 flex gap-2" aria-label="Pagination">
      <button
        className="rounded border border-border px-3 py-1 text-xs text-ink disabled:opacity-40"
        onClick={onPrevious}
        disabled={!hasPrevious}
      >
        Previous
      </button>
      <button
        className="rounded border border-border px-3 py-1 text-xs text-ink disabled:opacity-40"
        onClick={onNext}
        disabled={!hasNext}
      >
        Next
      </button>
    </nav>
  );
}

function useModalBehavior(
  open: boolean,
  onClose: () => void,
  containerRef: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    if (!open) return undefined;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const container = containerRef.current;
    if (!container) return undefined;
    const focusables = container.querySelectorAll<HTMLElement>(
      'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])',
    );
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    (first ?? container).focus();
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
      }
      if (event.key === "Tab") {
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previouslyFocused?.focus();
    };
  }, [open, onClose, containerRef]);
}

export function Drawer({
  open,
  title,
  children,
  onClose,
}: {
  open: boolean;
  title: string;
  children: ReactNode;
  onClose: () => void;
}) {
  const panelRef = useRef<HTMLElement>(null);
  useModalBehavior(open, onClose, panelRef);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40" role="presentation">
      <button
        className="absolute inset-0 bg-black/50"
        aria-label="Close drawer"
        onClick={onClose}
      />
      <aside
        ref={panelRef}
        className="absolute inset-y-0 right-0 flex w-full max-w-xl flex-col overflow-y-auto border-l border-border bg-surface p-5"
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
      >
        <header className="mb-4 flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          <button className="rounded p-1 text-muted hover:text-ink" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </header>
        {children}
      </aside>
    </div>
  );
}

export function Timeline({
  items,
}: {
  items: { title: string; detail?: string; time?: string }[];
}) {
  return (
    <ol className="space-y-3">
      {items.map((item, index) => (
        <li key={`${item.title}-${index}`} className="flex gap-3">
          <i className="mt-1.5 h-2 w-2 rounded-full bg-teal" />
          <div className="flex-1">
            <strong className="block text-sm text-ink">{item.title}</strong>
            {item.detail && <p className="text-sm text-muted">{item.detail}</p>}
          </div>
          {item.time && <time className="font-mono text-xs text-muted">{item.time}</time>}
        </li>
      ))}
    </ol>
  );
}

export function EvidenceCard({
  title,
  source,
  excerpt,
  meta,
}: {
  title: string;
  source: string;
  excerpt: string;
  meta?: ReactNode;
}) {
  return (
    <article className="rounded-lg border border-border bg-raised p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <SourceBadge source={source} />
        <span className="text-xs text-muted">{meta}</span>
      </div>
      <h3 className="text-sm font-medium text-ink">{title}</h3>
      <p className="mt-1 text-sm leading-6 text-muted">{excerpt}</p>
    </article>
  );
}

export function ConfirmationDialog({
  open,
  title,
  detail,
  confirmLabel = "Confirm",
  destructive = false,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  detail: string;
  confirmLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const dialogRef = useRef<HTMLDivElement>(null);
  useModalBehavior(open, onClose, dialogRef);
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/50" role="presentation">
      <div
        ref={dialogRef}
        className="w-full max-w-md rounded-xl border border-border bg-surface p-5"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="dialog-title"
        tabIndex={-1}
      >
        <h2 id="dialog-title" className="text-lg font-semibold text-ink">
          {title}
        </h2>
        <p className="mt-2 text-sm text-muted">{detail}</p>
        <footer className="mt-5 flex justify-end gap-2">
          <button className="rounded border border-border px-3 py-1.5 text-sm text-ink" onClick={onClose}>
            Cancel
          </button>
          <button
            className={`rounded px-3 py-1.5 text-sm ${
              destructive ? "bg-red-500/80 text-white" : "bg-teal text-bg"
            }`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </footer>
      </div>
    </div>
  );
}

export function Toast({
  message,
  tone = "success",
  onDismiss,
}: {
  message: string;
  tone?: "success" | "error" | "info";
  onDismiss?: () => void;
}) {
  const toneClass =
    tone === "error"
      ? "border-red-500/40 bg-red-500/10"
      : tone === "info"
        ? "border-navy/40 bg-navy/10"
        : "border-teal/40 bg-teal/10";
  return (
    <div className={`fixed right-4 bottom-4 z-50 flex items-center gap-3 rounded-lg border px-3 py-2 text-sm text-ink ${toneClass}`} role="status">
      <span>{message}</span>
      {onDismiss && (
        <button onClick={onDismiss} aria-label="Dismiss message">
          <X size={15} />
        </button>
      )}
    </div>
  );
}
