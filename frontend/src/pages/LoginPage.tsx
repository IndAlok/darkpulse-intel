import { ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { authApi } from "../lib/api";
import { setAccessToken } from "../lib/auth";
import type { Principal } from "../types/api";

export default function LoginPage({
  onAuthenticated,
}: {
  onAuthenticated: (principal: Principal) => void;
}) {
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const result = await authApi.login(token.trim());
      setAccessToken(result.data.token);
      onAuthenticated({ subject: result.data.subject, role: result.data.role });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Invalid access token");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-bg px-4">
      <form
        onSubmit={(event) => void submit(event)}
        className="w-full max-w-md rounded-2xl border border-border bg-surface p-8"
      >
        <div className="mb-6 flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-teal/15 text-teal">
            <ShieldCheck size={20} />
          </span>
          <div>
            <h1 className="text-xl font-semibold">DarkPulse</h1>
            <p className="text-sm text-muted">Investigator access</p>
          </div>
        </div>
        <label className="block text-sm text-muted" htmlFor="token">
          Access token
        </label>
        <input
          id="token"
          type="password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          className="mt-1 w-full rounded-lg border border-border bg-bg px-3 py-2 font-mono text-sm text-ink outline-none focus:border-teal"
          autoComplete="off"
          required
        />
        {error && <p className="mt-3 text-sm text-red-300">{error}</p>}
        <button
          type="submit"
          disabled={busy}
          className="mt-5 w-full rounded-lg bg-teal py-2 text-sm font-medium text-bg disabled:opacity-50"
        >
          {busy ? "Verifying…" : "Enter command center"}
        </button>
      </form>
    </div>
  );
}
