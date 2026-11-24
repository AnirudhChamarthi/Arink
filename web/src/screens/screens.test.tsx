import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";
import * as D from "../api/decoders";
import type { FactorEdit, RunRecord, Trace } from "../api/types";
import { createMockApi } from "../mocks/mockApi";
import resultQ1 from "../mocks/fixtures/run_result_q1_market.json";
import modelsJson from "../mocks/fixtures/models.json";
import { renderWith } from "../test/utils";
import { Home } from "./Home";
import { RunPage } from "./RunPage";
import { AssessmentTab } from "./run/AssessmentTab";
import { ReviewTab } from "./run/ReviewTab";
import { VariationsTab } from "./run/VariationsTab";
import { TraceViewer } from "./TraceViewer";
import { ApiProvider } from "../api/context";

const result = D.RunResult(resultQ1);
const models = D.arrayOf(D.ModelSpec)(modelsJson);
const fastApi = () => createMockApi({ latencyMs: 0, stepMs: 0 });

describe("Home", () => {
  it("lists the three questions with their default plan summary", async () => {
    renderWith(<Home />, { api: fastApi() });
    const headings = await screen.findAllByRole("heading", { level: 2, name: /\?$/ });
    expect(headings).toHaveLength(3);
    expect(headings[0].textContent).toMatch(/lose in a bad week/);
    expect(screen.getAllByText(/grid of up to/)).toHaveLength(3);
    const firstCard = headings[0].closest("article")!;
    expect(within(firstCard).getByText("q1.var")).toBeTruthy();
    expect(within(firstCard).getByText(/normal · student_t · historical · fhs · evt · montecarlo/)).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "Use sample dataset" })).toHaveLength(3);
  });

  it("loads a sample, validates it and shows findings by severity with the synthetic banner", async () => {
    renderWith(<Home />, { api: fastApi() });
    const [first] = await screen.findAllByRole("button", { name: "Use sample dataset" });
    await userEvent.click(first);
    expect(await screen.findByRole("button", { name: /Configure run/ })).toBeTruthy();
    expect(screen.getByText(/Synthetic data\./)).toBeTruthy();
    expect(screen.getByRole("region", { name: "info findings" })).toBeTruthy();
  });

  it("shows API errors as ErrorBody", async () => {
    const api = fastApi();
    api.questions = () => Promise.reject(new (class extends Error {})("boom"));
    renderWith(<Home />, { api });
    expect((await screen.findAllByRole("alert"))[0].textContent).toMatch(/boom/);
  });
});

describe("Run page overview", () => {
  it("renders metric ranges with units and trace links from the fixture", async () => {
    renderWith(<RunPage />, { api: fastApi(), route: "/runs/run-0001", path: "/runs/:runId" });
    expect(await screen.findByRole("tablist")).toBeTruthy();
    expect(screen.getByText("Awaiting review", { selector: ".badge" })).toBeTruthy();
    expect(screen.getByText(/Synthetic data\./)).toBeTruthy();
    const table = await screen.findByRole("table");
    const varRow = within(table).getByRole("rowheader", { name: /^VAR\s*Value at Risk/ }).closest("tr")!;
    const r = result.comparison.metric_ranges.var;
    const cells = within(varRow).getAllByRole("cell");
    expect(cells[0].textContent).toBe("% of gross exposure");
    expect(cells[1].textContent).toBe(`${(r.min * 100).toFixed(2)}%`);
    expect(cells[2].textContent).toBe(`${(r.median * 100).toFixed(2)}%`);
    const minLink = within(cells[1]).getByRole("link");
    expect(minLink.getAttribute("href")).toMatch(/^\/traces\/q1\.var-[0-9a-f]{12}#var$/);
    // Currency metrics keep thousands separators; counts of label values are shown.
    expect(screen.getByText("Outcome labels")).toBeTruthy();
  });
});

describe("Variations table", () => {
  it("sorts by a metric column in both directions and filters rows", async () => {
    render(
      <MemoryRouter>
        <VariationsTab result={result} specs={models} />
      </MemoryRouter>,
    );
    const table = screen.getByRole("table");
    const header = within(table).getByRole("columnheader", { name: "VAR" });
    const varIndex = within(table).getAllByRole("columnheader").indexOf(header);
    const column = () =>
      within(table)
        .getAllByRole("row")
        .slice(1)
        .map((row) => parseFloat(within(row).getAllByRole("cell")[varIndex].textContent!.replace(/[^\d.-]/g, "")));
    const grid = result.variations.filter((v) => v.spec.model_id === "q1.var").map((v) => v.output!.metrics.var.value * 100);

    await userEvent.click(within(header).getByRole("button"));
    expect(header.getAttribute("aria-sort")).toBe("ascending");
    const asc = column();
    expect(asc).toEqual([...asc].sort((a, b) => a - b));
    expect(asc[0]).toBeCloseTo(Math.min(...grid), 2);

    await userEvent.click(within(header).getByRole("button"));
    expect(header.getAttribute("aria-sort")).toBe("descending");
    const desc = column();
    expect(desc).toEqual([...desc].sort((a, b) => b - a));

    fireEvent.change(screen.getByLabelText("Filter"), { target: { value: "historical" } });
    const n = result.variations.filter((v) => v.spec.params.method === "historical").length;
    expect(within(table).getAllByRole("row")).toHaveLength(n + 1);
  });

  it("shows error rows", () => {
    const withError = structuredClone(result);
    withError.variations[0] = { ...withError.variations[0], output: null, error: "ValueError: singular covariance" };
    render(
      <MemoryRouter>
        <VariationsTab result={withError} specs={models} />
      </MemoryRouter>,
    );
    expect(screen.getByText(/ValueError: singular covariance/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "errors" } });
    expect(screen.getAllByRole("row")).toHaveLength(2);
  });
});

describe("Assessment edits", () => {
  const assessment = result.assessment;
  const factor = assessment.factors[0];

  it("produces a valid FactorEdit with only the changed fields and the mandatory reason", async () => {
    const onEdits = vi.fn<(e: FactorEdit[]) => void>();
    render(
      <MemoryRouter>
        <AssessmentTab assessment={assessment} canEdit edits={[]} onEditsChange={onEdits} />
      </MemoryRouter>,
    );
    expect(screen.getByText("Judgment", { selector: ".judgment-label" })).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: `Edit ${factor.name}` }));
    const form = screen.getByRole("form", { name: `Edit ${factor.name}` });
    await userEvent.selectOptions(within(form).getByLabelText("Likelihood (1–5)"), "5");
    await userEvent.selectOptions(within(form).getByLabelText("Control"), "weak");
    // Preview uses the shared rating rules: 5 x 3 = 15 -> high, weak control -> high.
    expect(within(form).getAllByText("high")).toHaveLength(2);

    await userEvent.click(within(form).getByRole("button", { name: "Add edit to review" }));
    expect(within(form).getByRole("alert").textContent).toMatch(/reason is required/);
    expect(onEdits).not.toHaveBeenCalled();

    await userEvent.type(within(form).getByLabelText(/Reason for change/), "Backtest exceptions cluster");
    await userEvent.click(within(form).getByRole("button", { name: "Add edit to review" }));
    expect(onEdits).toHaveBeenCalledTimes(1);
    const [edit] = onEdits.mock.calls[0][0];
    expect(edit).toEqual({ factor_id: factor.factor_id, likelihood: 5, control: "weak", reason: "Backtest exceptions cluster" });
    expect(D.FactorEdit(edit)).toEqual(edit);
  });

  it("hides editing when the run is not awaiting review", () => {
    render(
      <MemoryRouter>
        <AssessmentTab assessment={assessment} canEdit={false} edits={[]} onEditsChange={() => undefined} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("button", { name: /^Edit/ })).toBeNull();
  });
});

describe("Review", () => {
  const base = D.RunRecord(result.run);
  const renderReview = (run: RunRecord) =>
    renderWith(<ReviewTab run={run} edits={[]} factorNames={{}} onReviewed={() => undefined} />, { api: fastApi() });

  it.each(["pending", "running", "approved", "rejected", "failed"] as const)("disables approve/reject when %s", (status) => {
    renderReview({ ...base, status });
    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: "Reject" }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("enables them when awaiting_review and requires a reviewer name", async () => {
    renderReview({ ...base, status: "awaiting_review" });
    const approve = screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement;
    expect(approve.disabled).toBe(false);
    await userEvent.click(approve);
    expect(screen.getByRole("alert").textContent).toMatch(/reviewer's name/);
  });
});

describe("Trace viewer", () => {
  const trace: Trace = {
    trace_id: "q1.var-abcdef123456",
    model_id: "q1.var",
    title: "VaR <script>alert('x')</script>",
    assumptions: ["Returns are <b>i.i.d.</b>"],
    inputs: { params: { method: "normal", confidence: 0.99 } },
    steps: [
      { id: "sigma", title: "Portfolio volatility", formula: "\\sigma_p = \\sqrt{w^\\top \\Sigma w}", substitution: "sqrt(0.0004) <img src=x>", value: 0.02, unit: "fraction", table: [{ ticker: "AAA", weight: 0.6 }], note: "" },
      { id: "var", title: "VaR", formula: "\\mathrm{VaR} = z_{\\alpha}\\,\\sigma_p\\sqrt{h}", substitution: "2.326 \\times 0.02 \\times \\sqrt{5}", value: 0.104, unit: "fraction_of_gross", table: null, note: "Scaled by sqrt(h)." },
      { id: "bad", title: "Malformed", formula: "\\frac{1}{", substitution: "", value: null, unit: null, table: null, note: "" },
    ],
    result: { var: 0.104 },
    input_hash: "abcdef1234567890".repeat(4),
    warnings: ["Window shorter than requested"],
  };

  it("renders KaTeX formulas and escapes all other text", async () => {
    const api = fastApi();
    api.getTrace = async () => trace;
    const { container } = renderWith(<TraceViewer />, { api, route: "/traces/q1.var-abcdef123456#var", path: "/traces/:traceId" });
    expect(await screen.findByRole("heading", { level: 1 })).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("VaR <script>alert('x')</script>");
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
    expect(screen.getByText("Returns are <b>i.i.d.</b>")).toBeTruthy();
    expect(screen.getByText("sqrt(0.0004) <img src=x>")).toBeTruthy();
    // KaTeX output for formulas and the LaTeX substitution
    expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(3);
    expect(container.querySelector("#sigma .katex-mathml annotation")?.textContent).toBe("\\sigma_p = \\sqrt{w^\\top \\Sigma w}");
    // Malformed LaTeX does not throw: KaTeX renders an error span instead.
    expect(container.querySelector("#bad .katex-error, #bad .katex")).toBeTruthy();
    // Numbered steps, value + unit, table, warnings, hash and copy
    const steps = container.querySelectorAll(".trace-step");
    expect(steps).toHaveLength(3);
    expect(steps[1].classList.contains("targeted")).toBe(true);
    expect(within(steps[1] as HTMLElement).getByText("10.40%")).toBeTruthy();
    expect(screen.getByText("AAA")).toBeTruthy();
    expect(screen.getByText("Window shorter than requested")).toBeTruthy();
    expect(screen.getByText(trace.input_hash)).toBeTruthy();
    const writeText = vi.fn(async () => undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Copy input hash" }));
    });
    expect(writeText).toHaveBeenCalledWith(trace.input_hash);
  });

  it("shows not-found errors", async () => {
    render(
      <ApiProvider api={fastApi()}>
        <MemoryRouter initialEntries={["/traces/nope"]}>
          <TraceRoute />
        </MemoryRouter>
      </ApiProvider>,
    );
    expect(await screen.findByText("Trace not found", { exact: false })).toBeTruthy();
  });
});

import { Route, Routes } from "react-router-dom";
function TraceRoute() {
  return (
    <Routes>
      <Route path="/traces/:traceId" element={<TraceViewer />} />
    </Routes>
  );
}

describe("waitFor sanity", () => {
  it("mock api settles immediately with stepMs 0", async () => {
    const api = fastApi();
    const run = await api.startRun({ question: "q1_market", dataset: await api.sample("q1_market") });
    await waitFor(async () => expect((await api.getRun(run.run_id)).status).toBe("awaiting_review"));
  });
});
