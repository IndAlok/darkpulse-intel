import {
  Bell,
  Command,
  FileSearch,
  FileText,
  GitFork,
  Languages,
  LayoutDashboard,
  ListChecks,
  Map,
  Network,
  PanelLeft,
  Search,
  Settings2,
  ShieldCheck,
} from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, useLocation, useNavigate } from "react-router-dom";
import { alertsApi, healthApi } from "../lib/api";
import { clearAccessToken } from "../lib/auth";
import { formatRelative } from "../lib/formatters";
import { useApi } from "../hooks";
import type { Principal } from "../types/api";
import CommandPalette from "./CommandPalette";

const GROUPS = [
  {
    label: "Overview",
    items: [{ label: "Command center", path: "/", icon: LayoutDashboard, match: (p: string) => p === "/" }],
  },
  {
    label: "Investigate",
    items: [
      { label: "Intelligence", path: "/intel", icon: FileSearch, match: (p: string) => p.startsWith("/intel") },
      { label: "Search", path: "/search", icon: Search, match: (p: string) => p.startsWith("/search") },
      { label: "Actors", path: "/actors", icon: Network, match: (p: string) => p.startsWith("/actors") },
      { label: "Actor graph", path: "/graph", icon: GitFork, match: (p: string) => p.startsWith("/graph") },
      { label: "Surat map", path: "/map", icon: Map, match: (p: string) => p.startsWith("/map") },
    ],
  },
  {
    label: "Monitor",
    items: [
      { label: "Alerts", path: "/alerts", icon: Bell, match: (p: string) => p.startsWith("/alerts") },
      { label: "Watchlists", path: "/watchlists", icon: ListChecks, match: (p: string) => p.startsWith("/watchlists") },
      { label: "Slang review", path: "/slang", icon: Languages, match: (p: string) => p.startsWith("/slang") },
    ],
  },
  {
    label: "Evidence",
    items: [
      { label: "Reports & export", path: "/reports", icon: FileText, match: (p: string) => p.startsWith("/reports") },
      { label: "Evidence workspace", path: "/evidence", icon: ShieldCheck, match: (p: string) => p.startsWith("/evidence") },
    ],
  },
  {
    label: "Operations",
    items: [{ label: "System status", path: "/operations", icon: Settings2, match: (p: string) => p.startsWith("/operations") }],
  },
];

function chipTone(status?: string) {
  if (status === "healthy" || status === "green" || status === "yellow") return "bg-teal/15 text-teal";
  if (status === "never_run") return "bg-amber-500/15 text-amber-200";
  return "bg-red-500/15 text-red-300";
}

export default function Shell({
  principal,
  children,
}: {
  principal: Principal;
  children: ReactNode;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  const health = useApi(() => healthApi.detailed());
  const alerts = useApi(() => alertsApi.history());
  const unread = (alerts.data?.data ?? []).filter((item) => !item.acknowledged).length;
  const services = health.data?.services ?? {};

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setPaletteOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex min-h-screen bg-bg text-ink">
      <aside
        className={`sticky top-0 flex h-screen shrink-0 flex-col border-r border-border bg-surface ${
          collapsed ? "w-[72px]" : "w-64"
        }`}
      >
        <div className="flex items-center gap-3 border-b border-border px-4 py-4">
          <span className="grid h-9 w-9 place-items-center rounded-lg bg-teal/15 text-teal">
            <ShieldCheck size={18} />
          </span>
          {!collapsed && (
            <div>
              <strong className="block text-sm">DarkPulse</strong>
              <span className="text-xs text-muted">Command center</span>
            </div>
          )}
        </div>
        <nav className="flex-1 overflow-y-auto px-2 py-3" aria-label="Primary navigation">
          {GROUPS.map((group) => (
            <section key={group.label} className="mb-4">
              {!collapsed && (
                <p className="px-2 pb-1 font-mono text-[10px] tracking-[0.18em] text-muted uppercase">
                  {group.label}
                </p>
              )}
              {group.items.map(({ label, path, icon: Icon, match }) => (
                <NavLink
                  key={path}
                  to={path}
                  className={`mb-0.5 flex items-center gap-3 rounded-lg px-3 py-2 text-sm ${
                    match(location.pathname)
                      ? "bg-raised text-teal"
                      : "text-muted hover:bg-raised hover:text-ink"
                  }`}
                >
                  <Icon size={16} />
                  {!collapsed && <span>{label}</span>}
                </NavLink>
              ))}
            </section>
          ))}
        </nav>
        <div className="border-t border-border p-3 text-xs text-muted">
          Policy-controlled collection
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-border bg-surface/80 px-4 py-3 backdrop-blur">
          <button
            className="rounded border border-border p-1.5 text-muted hover:text-ink"
            onClick={() => setCollapsed((value) => !value)}
            aria-label="Collapse sidebar"
          >
            <PanelLeft size={16} />
          </button>
          <button
            className="flex min-w-0 flex-1 items-center gap-2 rounded-lg border border-border bg-bg px-3 py-2 text-left text-sm text-muted"
            onClick={() => setPaletteOpen(true)}
          >
            <Search size={15} />
            <span className="flex-1 truncate">Search or jump…</span>
            <kbd className="hidden items-center gap-1 rounded border border-border px-1.5 font-mono text-[10px] sm:inline-flex">
              <Command size={10} />K
            </kbd>
          </button>
          <div className="hidden items-center gap-1 lg:flex">
            {(["mongodb", "neo4j", "processor", "collector"] as const).map((key) => {
              const service = services[key];
              const label =
                key === "collector"
                  ? `collector ${formatRelative(service?.last_started_at)}`
                  : key;
              return (
                <span
                  key={key}
                  className={`rounded-full px-2 py-0.5 font-mono text-[10px] ${chipTone(service?.status)}`}
                >
                  {label}
                </span>
              );
            })}
          </div>
          <button
            className="relative rounded border border-border p-1.5 text-muted hover:text-ink"
            onClick={() => navigate("/alerts")}
            aria-label="View alerts"
          >
            <Bell size={16} />
            {unread > 0 && (
              <b className="absolute -top-1 -right-1 rounded-full bg-red-500 px-1 text-[10px] text-white">
                {Math.min(unread, 99)}
              </b>
            )}
          </button>
          <div className="text-right">
            <strong className="block text-xs text-ink">{principal.subject}</strong>
            <small className="text-[11px] text-muted">{principal.role}</small>
          </div>
          <button
            className="text-xs text-muted hover:text-ink"
            onClick={() => {
              clearAccessToken();
              window.location.assign("/login");
            }}
          >
            Sign out
          </button>
        </header>
        <main className="flex-1 overflow-x-hidden p-5">{children}</main>
      </div>
      <CommandPalette open={paletteOpen} onClose={() => setPaletteOpen(false)} />
      <Link to="#main" className="sr-only">
        Skip
      </Link>
    </div>
  );
}
