import { Bell, Command, Search } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useNavigate } from "react-router-dom";
import { alertsApi, healthApi } from "../lib/api";
import { useApi } from "../hooks";

export default function Topbar() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const health = useApi(() => healthApi.detailed());
  const alerts = useApi(() => alertsApi.history());
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim()) navigate(`/search?q=${encodeURIComponent(query.trim())}`);
  };
  const alertCount = alerts.data?.data.length ?? 0;
  const healthyStates = new Set(["healthy", "green", "yellow"]);
  const healthy = Boolean(
    health.data &&
      (healthyStates.has(health.data.status) ||
        (health.data.services
          ? Object.values(health.data.services).every(
              (service) => !service.status || healthyStates.has(service.status),
            )
          : false)),
  );
  return (
    <header className="topbar">
      <form className="global-search" onSubmit={submit}>
        <Search size={17} />
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search intelligence, vendors, or locations"
          aria-label="Global intelligence search"
        />
        <kbd>
          <Command size={11} />K
        </kbd>
      </form>
      <div className="topbar-actions">
        <span className={`service-status ${healthy ? "healthy" : "degraded"}`}>
          <i />
          {health.loading
            ? "Checking systems"
            : healthy
              ? "Systems online"
              : "Systems degraded"}
        </span>
        <button
          className="icon-button notification-button"
          onClick={() => navigate("/alerts")}
          aria-label="View alerts"
        >
          <Bell size={18} />
          {alertCount > 0 && <b>{Math.min(alertCount, 99)}</b>}
        </button>
        <div className="analyst-menu">
          <span>
            <Command size={14} />
          </span>
          <div>
            <strong>Analyst desk</strong>
            <small>Investigator console</small>
          </div>
        </div>
      </div>
    </header>
  );
}
