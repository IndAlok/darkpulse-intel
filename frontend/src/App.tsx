import { useEffect, useState } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";
import Shell from "./components/Shell";
import { authApi } from "./lib/api";
import { UNAUTHENTICATED_EVENT, getAccessToken } from "./lib/auth";
import type { Principal } from "./types/api";
import LoginPage from "./pages/LoginPage";
import DashboardPage from "./pages/DashboardPage";
import IntelFeedPage from "./pages/IntelFeedPage";
import SearchPage from "./pages/SearchPage";
import ActorsPage from "./pages/ActorsPage";
import ActorProfilePage from "./pages/ActorProfilePage";
import ActorGraphPage from "./pages/ActorGraphPage";
import SuratMapPage from "./pages/SuratMapPage";
import AlertsPage from "./pages/AlertsPage";
import ReportsPage from "./pages/ReportsPage";
import EvidencePage from "./pages/EvidencePage";
import WatchlistsPage from "./pages/WatchlistsPage";
import SlangPage from "./pages/SlangPage";
import OperationsPage from "./pages/OperationsPage";
import NotFoundPage from "./pages/NotFoundPage";

export default function App() {
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const bootstrap = async () => {
      if (!getAccessToken()) {
        if (!cancelled) {
          setPrincipal(null);
          setReady(true);
        }
        return;
      }
      try {
        const me = await authApi.me();
        if (!cancelled) setPrincipal(me.data);
      } catch {
        if (!cancelled && !getAccessToken()) setPrincipal(null);
      } finally {
        if (!cancelled) setReady(true);
      }
    };
    void bootstrap();
    const onUnauth = () => setPrincipal(null);
    window.addEventListener(UNAUTHENTICATED_EVENT, onUnauth);
    return () => {
      cancelled = true;
      window.removeEventListener(UNAUTHENTICATED_EVENT, onUnauth);
    };
  }, []);

  if (!ready) {
    return (
      <div className="grid min-h-screen place-items-center bg-bg text-muted">
        Checking session…
      </div>
    );
  }

  if (!principal) {
    return <LoginPage onAuthenticated={setPrincipal} />;
  }

  return (
    <BrowserRouter>
      <Shell principal={principal}>
        <ErrorBoundary>
          <Routes>
            <Route path="/" element={<DashboardPage principal={principal} />} />
            <Route path="/login" element={<Navigate to="/" replace />} />
            <Route path="/intel" element={<IntelFeedPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/actors" element={<ActorsPage />} />
            <Route path="/actors/:actorId" element={<ActorProfilePage />} />
            <Route path="/graph" element={<ActorGraphPage />} />
            <Route path="/map" element={<SuratMapPage />} />
            <Route path="/alerts" element={<AlertsPage />} />
            <Route path="/reports" element={<ReportsPage />} />
            <Route path="/evidence" element={<EvidencePage />} />
            <Route path="/watchlists" element={<WatchlistsPage />} />
            <Route path="/slang" element={<SlangPage />} />
            <Route path="/operations" element={<OperationsPage principal={principal} />} />
            <Route path="*" element={<NotFoundPage />} />
          </Routes>
        </ErrorBoundary>
      </Shell>
    </BrowserRouter>
  );
}
