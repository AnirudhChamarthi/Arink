import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { POLL_INTERVAL_MS, toErrorBody, type RiskbotApi } from "./client";
import type { ErrorBody } from "./types";

interface ApiConfig {
  api: RiskbotApi;
  pollMs: number;
}

const ApiContext = createContext<ApiConfig | null>(null);

export function ApiProvider({ api, pollMs = POLL_INTERVAL_MS, children }: { api: RiskbotApi; pollMs?: number; children: ReactNode }) {
  return <ApiContext.Provider value={{ api, pollMs }}>{children}</ApiContext.Provider>;
}

export function useApiConfig(): ApiConfig {
  const ctx = useContext(ApiContext);
  if (!ctx) throw new Error("useApi must be used inside <ApiProvider>");
  return ctx;
}

export function useApi(): RiskbotApi {
  return useApiConfig().api;
}

export type AsyncState<A> =
  | { status: "loading"; data?: undefined; error?: undefined }
  | { status: "error"; data?: undefined; error: ErrorBody }
  | { status: "ready"; data: A; error?: undefined };

/**
 * Run `load` when `deps` change; exposes loading / error / ready and a `reload`.
 * Late responses from superseded requests are ignored.
 */
export function useAsync<A>(load: (api: RiskbotApi) => Promise<A>, deps: unknown[]): AsyncState<A> & { reload: () => void } {
  const api = useApi();
  const [state, setState] = useState<AsyncState<A>>({ status: "loading" });
  const [nonce, setNonce] = useState(0);
  const loadRef = useRef(load);
  loadRef.current = load;
  useEffect(() => {
    let live = true;
    setState((s) => (s.status === "ready" ? s : { status: "loading" }));
    loadRef.current(api).then(
      (data) => live && setState({ status: "ready", data }),
      (err) => live && setState({ status: "error", error: toErrorBody(err) }),
    );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, nonce, ...deps]);
  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { ...state, reload };
}
