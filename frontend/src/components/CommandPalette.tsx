import { Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

const ROUTES = [
  { label: "Command center", path: "/", hint: "overview" },
  { label: "Intelligence", path: "/intel", hint: "feed" },
  { label: "Search", path: "/search", hint: "query" },
  { label: "Actors", path: "/actors", hint: "vendors" },
  { label: "Actor graph", path: "/graph", hint: "network" },
  { label: "Surat map", path: "/map", hint: "geo" },
  { label: "Alerts", path: "/alerts", hint: "live" },
  { label: "Watchlists", path: "/watchlists", hint: "terms" },
  { label: "Slang review", path: "/slang", hint: "dictionary" },
  { label: "Reports", path: "/reports", hint: "export" },
  { label: "Evidence", path: "/evidence", hint: "seal" },
  { label: "Operations", path: "/operations", hint: "collector" },
];

export default function CommandPalette({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return ROUTES;
    return ROUTES.filter(
      (item) =>
        item.label.toLowerCase().includes(needle) ||
        item.hint.includes(needle) ||
        item.path.includes(needle),
    );
  }, [query]);

  useEffect(() => {
    if (!open) setQuery("");
  }, [open]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 grid place-items-start bg-black/55 pt-[12vh]" role="presentation">
      <button className="absolute inset-0" aria-label="Close command palette" onClick={onClose} />
      <div
        className="relative w-full max-w-xl rounded-xl border border-border bg-surface shadow-2xl"
        role="dialog"
        aria-label="Command palette"
      >
        <div className="flex items-center gap-2 border-b border-border px-3">
          <Search size={16} className="text-muted" />
          <input
            autoFocus
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Escape") onClose();
              if (event.key === "Enter") {
                const first = matches[0];
                if (query.trim() && !ROUTES.some((item) => item.label.toLowerCase() === query.trim().toLowerCase())) {
                  navigate(`/search?q=${encodeURIComponent(query.trim())}`);
                  onClose();
                  return;
                }
                if (first) {
                  navigate(first.path);
                  onClose();
                }
              }
            }}
            placeholder="Jump to a desk or search intelligence"
            className="w-full bg-transparent py-3 text-sm text-ink outline-none"
          />
        </div>
        <ul className="max-h-80 overflow-y-auto p-2">
          {matches.map((item) => (
            <li key={item.path}>
              <button
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-ink hover:bg-raised"
                onClick={() => {
                  navigate(item.path);
                  onClose();
                }}
              >
                <span>{item.label}</span>
                <span className="font-mono text-[11px] text-muted">{item.path}</span>
              </button>
            </li>
          ))}
          {query.trim() ? (
            <li>
              <button
                className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm text-teal hover:bg-raised"
                onClick={() => {
                  navigate(`/search?q=${encodeURIComponent(query.trim())}`);
                  onClose();
                }}
              >
                Search intel for “{query.trim()}”
              </button>
            </li>
          ) : null}
        </ul>
      </div>
    </div>
  );
}
