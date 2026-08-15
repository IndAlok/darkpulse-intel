import { Link, useLocation } from "react-router-dom";
import {
  Bell,
  FileText,
  Languages,
  LayoutDashboard,
  Map,
  Network,
  Search,
  Settings2,
  ShieldCheck,
  ListChecks,
} from "lucide-react";

const GROUPS = [
  {
    label: "Overview",
    items: [{ label: "Command center", path: "/", icon: LayoutDashboard }],
  },
  {
    label: "Investigate",
    items: [
      { label: "Intelligence", path: "/intel", icon: Search },
      { label: "Search", path: "/search", icon: Search },
      { label: "Actors", path: "/actors", icon: Network },
      { label: "Actor graph", path: "/graph", icon: Network },
      { label: "Surat map", path: "/map", icon: Map },
    ],
  },
  {
    label: "Monitor",
    items: [
      { label: "Alerts", path: "/alerts", icon: Bell },
      { label: "Watchlists", path: "/watchlists", icon: ListChecks },
      { label: "Slang review", path: "/slang", icon: Languages },
    ],
  },
  {
    label: "Evidence",
    items: [
      { label: "Reports & export", path: "/reports", icon: FileText },
      { label: "Evidence workspace", path: "/evidence", icon: ShieldCheck },
    ],
  },
  {
    label: "Operations",
    items: [{ label: "System status", path: "/operations", icon: Settings2 }],
  },
];

export default function Sidebar() {
  const currentPath = useLocation().pathname;
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-mark">
          <ShieldCheck size={21} />
        </span>
        <div>
          <strong>DarkPulse</strong>
          <span>Investigator workspace</span>
        </div>
      </div>
      <nav aria-label="Primary navigation" className="sidebar-nav">
        {GROUPS.map((group) => (
          <section className="nav-group" key={group.label}>
            <p>{group.label}</p>
            {group.items.map(({ label, path, icon: Icon }) => (
              <Link
                key={path}
                to={path}
                className={`sidebar-link ${currentPath === path ? "active" : ""}`}
              >
                <Icon size={17} />
                <span>{label}</span>
              </Link>
            ))}
          </section>
        ))}
      </nav>
      <div className="sidebar-footer">
        <span className="footer-dot" />
        Policy-controlled collection
      </div>
    </aside>
  );
}
