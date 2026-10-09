import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { ErrorBoundary } from "./components/ErrorBoundary";
import Shell from "./components/Shell";
import { ApiRequestError, authApi } from "./lib/api";
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

function RoutedBoundary({ children }: { children: ReactNode }) {
  const location = useLocation();
  return <ErrorBoundary key={location.pathname}>{children}</ErrorBoundary>;
}

export default function App() {
  const [principal, setPrincipal] = useState<Principal | null>(null);
  const [ready, setReady] = useState(false);
  const [bootError, setBootError] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const bootstrap = async () => {
      try {
        const me = await authApi.me();
        if (!cancelled) {
          setPrincipal(me.data);
          setBootError(false);
        }
      } catch (error) {
        if (cancelled) return;
        setPrincipal(null);
        const unauthenticated = error instanceof ApiRequestError && error.status === 401;
        setBootError(!unauthenticated && Boolean(getAccessToken()));
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
  }, [attempt]);

  if (!ready) {
    return (
      <div className="grid min-h-screen place-items-center bg-bg text-muted">
        Checking session…
      </div>
    );
  }

  if (!principal && bootError) {
    return (
      <div className="grid min-h-screen place-items-center bg-bg text-muted">
        <div className="text-center">
          <p>Could not check the session.</p>
          <button
            className="mt-3 rounded bg-teal px-3 py-1.5 text-sm text-bg"
            onClick={() => setAttempt((value) => value + 1)}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (!principal) {
    return <LoginPage onAuthenticated={setPrincipal} />;
  }

  return (
    <BrowserRouter>
      <Shell principal={principal}>
        <RoutedBoundary>
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
        </RoutedBoundary>
      </Shell>
    </BrowserRouter>
  );
}
