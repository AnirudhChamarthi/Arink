/**
 * Mock-mode smoke test: the whole app on the fixture-backed mock API.
 * Home -> sample dataset -> plan editor -> start run -> polling to awaiting_review -> approve -> report.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { MemoryRouter } from "react-router-dom";
import { ApiProvider } from "./api/context";
import { AppRoutes, Shell } from "./App";
import { DraftProvider } from "./lib/draft";
import { createMockApi } from "./mocks/mockApi";

describe("mock mode smoke", () => {
  it("starts a run, waits for review, approves it and shows the report", async () => {
    const api = createMockApi({ latencyMs: 0, stepMs: 25, seedRuns: false });
    const user = userEvent.setup();
    render(
      <ApiProvider api={api} pollMs={10}>
        <DraftProvider>
          <MemoryRouter>
            <Shell api={api}>
              <AppRoutes />
            </Shell>
          </MemoryRouter>
        </DraftProvider>
      </ApiProvider>,
    );
    expect(screen.getByText(/Mock mode: the browser serves/)).toBeTruthy();
    expect(await screen.findByText("No runs yet")).toBeTruthy();

    // Home: sample dataset for Q2, validated.
    const buttons = await screen.findAllByRole("button", { name: "Use sample dataset" });
    await user.click(buttons[1]);
    await user.click(await screen.findByRole("button", { name: /Configure run/ }));

    // Plan editor: default plan, preview, use_llm off by default.
    expect(await screen.findByText(/Grid ·/)).toBeTruthy();
    expect((screen.getByRole("switch") as HTMLInputElement).checked).toBe(false);
    const preview = screen.getByRole("complementary", { name: "Variation preview" });
    expect(within(preview).getByText("35")).toBeTruthy(); // 32 grid + 3 extras
    const start = screen.getByRole("button", { name: "Start run" });
    await user.click(start);

    // Run page: polls through pending/running to awaiting_review.
    await waitFor(() => expect(screen.getByText("Awaiting review", { selector: ".badge" })).toBeTruthy(), { timeout: 4000 });
    expect(screen.getByRole("tab", { name: "Overview", selected: true })).toBeTruthy();
    expect(screen.getByText(/Synthetic data\./)).toBeTruthy();

    // Review: approve with a reviewer name.
    await user.click(screen.getByRole("tab", { name: "Review" }));
    await user.type(await screen.findByLabelText(/Reviewer name/), "A. Analyst");
    await user.type(screen.getByLabelText("Comment"), "Reasonable for a demo.");
    await user.click(screen.getByRole("button", { name: "Approve" }));
    await waitFor(() => expect(screen.getByText("Approved", { selector: ".run-title .badge" })).toBeTruthy());
    expect((screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement).disabled).toBe(true);

    // Report: signed off, markdown rendered safely, downloadable.
    await user.click(screen.getByRole("tab", { name: "Report" }));
    expect(await screen.findByRole("button", { name: "Download .md" })).toBeTruthy();
    expect(screen.getByText("A. Analyst", { selector: "strong" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Sign-off" })).toBeTruthy();

    // Audit log records the review.
    await user.click(screen.getByRole("tab", { name: "Audit log" }));
    expect(await screen.findByText("Review submitted")).toBeTruthy();
  });
});
