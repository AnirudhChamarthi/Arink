import type { To } from "react-router-dom";

/** Link target for a trace, optionally scrolled to a step (`/traces/:id#step`). */
export function traceHref(traceId: string, step?: string | null): To {
  return { pathname: `/traces/${encodeURIComponent(traceId)}`, hash: step ? `#${encodeURIComponent(step)}` : "" };
}

export function runHref(runId: string, tab?: string): string {
  return `/runs/${encodeURIComponent(runId)}${tab ? `/${tab}` : ""}`;
}
