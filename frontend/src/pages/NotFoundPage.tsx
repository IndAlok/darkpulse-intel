import { Link } from "react-router-dom";

export default function NotFoundPage() {
  return (
    <div className="rounded-xl border border-border bg-surface p-8">
      <p className="font-mono text-xs tracking-widest text-teal uppercase">404</p>
      <h1 className="mt-2 text-2xl font-semibold">This desk does not exist</h1>
      <p className="mt-2 text-sm text-muted">
        The path is not a DarkPulse route. Return to the command center or open search.
      </p>
      <div className="mt-5 flex gap-3">
        <Link to="/" className="rounded bg-teal px-3 py-1.5 text-sm text-bg">
          Command center
        </Link>
        <Link to="/search" className="rounded border border-border px-3 py-1.5 text-sm text-ink">
          Search
        </Link>
      </div>
    </div>
  );
}
