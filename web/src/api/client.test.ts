import { describe, expect, it, vi } from "vitest";
import { ApiError, createHttpApi, pollRun, type RiskbotApi } from "./client";
import type { RunRecord, RunStatus } from "./types";
import questions from "../mocks/fixtures/questions.json";
import notFound from "../mocks/fixtures/error_not_found.json";
import record from "../mocks/fixtures/run_record_q1_market.json";

function respond(status: number, body: unknown, raw = false) {
  return new Response(raw ? (body as string) : JSON.stringify(body), { status, headers: { "Content-Type": raw ? "text/html" : "application/json" } });
}

describe("http client", () => {
  it("calls the route under the base URL and decodes the response", async () => {
    const fetchMock = vi.fn(async () => respond(200, questions));
    const api = createHttpApi("http://api.test/v2/", fetchMock as unknown as typeof fetch);
    const qs = await api.questions();
    expect(fetchMock).toHaveBeenCalledWith("http://api.test/v2/questions", expect.objectContaining({ method: "GET" }));
    expect(qs.map((q) => q.question)).toEqual(["q1_market", "q2_balance_sheet", "q3_transition"]);
  });

  it("sends JSON bodies and encodes path segments", async () => {
    const fetchMock = vi.fn(async () => respond(200, record));
    const api = createHttpApi("http://api.test/v2", fetchMock as unknown as typeof fetch);
    await api.submitReview("run/1", { decision: "approve", reviewer: "Ana" });
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://api.test/v2/runs/run%2F1/review");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ decision: "approve", reviewer: "Ana" });
    expect((init.headers as Record<string, string>)["Content-Type"]).toBe("application/json");
  });

  it("throws ApiError carrying the ErrorBody", async () => {
    const api = createHttpApi("http://api.test/v2", (async () => respond(404, notFound)) as unknown as typeof fetch);
    const err = await api.getRun("x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(404);
    expect(err.code).toBe("not_found");
    expect(err.message).toBe("unknown run 'x'");
  });

  it("maps a conflict ErrorBody", async () => {
    const body = { code: "conflict", message: "run r is running", details: {} };
    const api = createHttpApi("http://api.test/v2", (async () => respond(409, body)) as unknown as typeof fetch);
    await expect(api.getResult("r")).rejects.toMatchObject({ status: 409, body });
  });

  it("turns non-ErrorBody failures and network errors into ErrorBody", async () => {
    const api = createHttpApi("http://api.test/v2", (async () => respond(502, "<html>Bad gateway</html>", true)) as unknown as typeof fetch);
    await expect(api.questions()).rejects.toMatchObject({ status: 502, body: { code: "internal" } });
    const down = createHttpApi("http://api.test/v2", (async () => {
      throw new TypeError("Failed to fetch");
    }) as unknown as typeof fetch);
    await expect(down.questions()).rejects.toMatchObject({ status: 0, body: { code: "internal", message: expect.stringMatching(/Cannot reach/) } });
  });

  it("rejects a response that does not match the contract", async () => {
    const api = createHttpApi("http://api.test/v2", (async () => respond(200, { ...record, status: "weird" })) as unknown as typeof fetch);
    await expect(api.getRun("run-0001")).rejects.toThrow(/RunRecord\.status/);
  });
});

describe("pollRun", () => {
  const seq = (statuses: RunStatus[]) => {
    let i = 0;
    const getRun = vi.fn(async (): Promise<RunRecord> => ({ ...(record as RunRecord), status: statuses[Math.min(i++, statuses.length - 1)] }));
    return { api: { getRun } as unknown as RiskbotApi, getRun };
  };

  it("polls until awaiting_review and stops", async () => {
    const { api, getRun } = seq(["pending", "running", "running", "awaiting_review", "approved"]);
    const updates: RunStatus[] = [];
    const final = await pollRun(api, "run-0001", { intervalMs: 1, onUpdate: (r) => updates.push(r.status) });
    expect(final.status).toBe("awaiting_review");
    expect(getRun).toHaveBeenCalledTimes(4);
    expect(updates).toEqual(["pending", "running", "running", "awaiting_review"]);
  });

  it.each(["approved", "rejected", "failed"] as RunStatus[])("stops immediately on %s", async (status) => {
    const { api, getRun } = seq([status]);
    await expect(pollRun(api, "r", { intervalMs: 1 })).resolves.toMatchObject({ status });
    expect(getRun).toHaveBeenCalledTimes(1);
  });

  it("waits 1.5 s between polls by default", async () => {
    vi.useFakeTimers();
    try {
      const { api, getRun } = seq(["running", "awaiting_review"]);
      const p = pollRun(api, "r");
      await vi.advanceTimersByTimeAsync(1000);
      expect(getRun).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(600);
      expect(getRun).toHaveBeenCalledTimes(2);
      await expect(p).resolves.toMatchObject({ status: "awaiting_review" });
    } finally {
      vi.useRealTimers();
    }
  });

  it("can be aborted", async () => {
    const { api } = seq(["running"]);
    const ctrl = new AbortController();
    const p = pollRun(api, "r", { intervalMs: 50, signal: ctrl.signal });
    setTimeout(() => ctrl.abort(), 5);
    await expect(p).rejects.toMatchObject({ name: "AbortError" });
  });
});
