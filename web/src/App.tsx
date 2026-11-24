import { lazy, Suspense, useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Link, NavLink, Route, Routes } from "react-router-dom";
import type { RiskbotApi } from "./api/client";
import { ApiProvider, useAsync } from "./api/context";
import { Empty, Loading } from "./components/ui";
import { DraftProvider } from "./lib/draft";
import { Home } from "./screens/Home";
import { NewRun } from "./screens/NewRun";
import { RunPage } from "./screens/RunPage";

// KaTeX is only needed on the trace screen: load it on demand.
const TraceViewer = lazy(() => import("./screens/TraceViewer"));

type Theme = "light" | "dark" | "system";

function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(() => (localStorage.getItem("riskbot-theme") as Theme | null) ?? "system");
  useEffect(() => {
    const root = document.documentElement;
    if (theme === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", theme);
    localStorage.setItem("riskbot-theme", theme);
  }, [theme]);
  return (
    <label className="theme-toggle">
      <span className="visually-hidden">Colour theme</span>
      <select value={theme} onChange={(e) => setTheme(e.target.value as Theme)}>
        <option value="system">System theme</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}

function Connection({ api }: { api: RiskbotApi }) {
  const health = useAsync((a) => a.health(), []);
  const state = health.status === "ready" ? "ok" : health.status === "error" ? "down" : "checking";
  return (
    <span className={`conn conn-${state}`} title={api.mode === "mock" ? "Serving contract fixtures in the browser" : api.baseUrl}>
      <span className="conn-dot" aria-hidden="true" />
      {api.mode === "mock" ? "Mock mode" : "API"}
      <span className="visually-hidden">
        {state === "ok" ? " connected" : state === "down" ? " unreachable" : " checking"}
      </span>
      {health.status === "ready" && <span className="conn-version">v{health.data.contract_version}</span>}
    </span>
  );
}

export function AppRoutes() {
  return (
    <Suspense fallback={<div className="page"><Loading /></div>}>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/new/:question" element={<NewRun />} />
        <Route path="/runs/:runId" element={<RunPage />} />
        <Route path="/runs/:runId/:tab" element={<RunPage />} />
        <Route path="/traces/:traceId" element={<TraceViewer />} />
        <Route
          path="*"
          element={
            <div className="page">
              <Empty title="Page not found">
                <Link to="/">Back to the questions</Link>
              </Empty>
            </div>
          }
        />
      </Routes>
    </Suspense>
  );
}

export function Shell({ api, children }: { api: RiskbotApi; children: ReactNode }) {
  return (
    <>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <header className="topbar">
        <Link to="/" className="brand" aria-label="Riskbot home">
          <span className="brand-mark" aria-hidden="true">R</span>
          <span className="brand-name">Riskbot</span>
          <span className="brand-sub">risk analysis workbench</span>
        </Link>
        <nav aria-label="Main" className="topnav">
          <NavLink to="/" end>
            Questions
          </NavLink>
        </nav>
        <div className="topbar-right">
          <Connection api={api} />
          <ThemeToggle />
        </div>
      </header>
      {api.mode === "mock" && (
        <div className="banner banner-mock" role="note">
          Mock mode: the browser serves the contract's example payloads; numbers are placeholders and no backend is called.
        </div>
      )}
      <main id="main" tabIndex={-1}>
        {children}
      </main>
      <footer className="footer small muted">
        Riskbot v2 · figures link to their calculation traces · qualitative ratings are labelled judgment · not investment advice
      </footer>
    </>
  );
}

export function App({ api, pollMs }: { api: RiskbotApi; pollMs?: number }) {
  return (
    <ApiProvider api={api} pollMs={pollMs}>
      <DraftProvider>
        <BrowserRouter>
          <Shell api={api}>
            <AppRoutes />
          </Shell>
        </BrowserRouter>
      </DraftProvider>
    </ApiProvider>
  );
}
