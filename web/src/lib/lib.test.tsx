import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import * as D from "../api/decoders";
import questionsJson from "../mocks/fixtures/questions.json";
import modelsJson from "../mocks/fixtures/models.json";
import { formatParam, formatValue, humanize, unitLabel } from "./format";
import { Markdown, safeHref } from "./markdown";
import { cartesianCount, effectiveGridCount, planProblems } from "./plan";
import { inherentRating, overallRating, rate, residualRating } from "./rules";

describe("formatValue", () => {
  it("formats fractions as percentages", () => {
    expect(formatValue(0.07, "fraction")).toBe("7.00%");
    expect(formatValue(0.051475, "fraction_of_gross")).toBe("5.15%");
    expect(formatValue(-0.1234, "fraction")).toBe("−12.34%");
    expect(formatValue(0.000042, "fraction")).toBe("0.0042%");
  });
  it("formats basis points", () => {
    expect(formatValue(300, "bp")).toBe("300 bp");
    expect(formatValue(-1250, "bp")).toBe("−1,250 bp");
    expect(formatValue(12.34, "bp")).toBe("12.3 bp");
  });
  it("formats currency with separators", () => {
    expect(formatValue(1234567.89, "currency", { currency: "USD" })).toBe("$1,234,568");
    expect(formatValue(-2500000, "currency", { currency: "EUR" })).toBe("−€2,500,000");
    expect(formatValue(12.5, "currency", { currency: "USD" })).toBe("$12.50");
    expect(formatValue(9876543, "currency")).toBe("9,876,543");
  });
  it("formats other units", () => {
    expect(formatValue(12, "count")).toBe("12");
    expect(formatValue(12000, "count")).toBe("12,000");
    expect(formatValue(1.2, "ratio")).toBe("1.20");
    expect(formatValue(0.0412, "probability")).toBe("0.041");
    expect(formatValue(123456, "tCO2e")).toBe("123,456 tCO₂e");
    expect(formatValue(212.34, "tCO2e_per_musd")).toBe("212.3 tCO₂e/$m");
    expect(formatValue(780, "days")).toBe("780 days");
    expect(formatValue(3.25, "years")).toBe("3.25 yrs");
  });
  it("handles missing and signed values", () => {
    expect(formatValue(null, "fraction")).toBe("—");
    expect(formatValue(Number.NaN, "fraction")).toBe("—");
    expect(formatValue(0.02, "fraction", { signed: true })).toBe("+2.00%");
  });
  it("labels units and parameters", () => {
    expect(unitLabel("fraction_of_gross")).toBe("% of gross exposure");
    expect(unitLabel("currency", "GBP")).toBe("GBP");
    expect(humanize("delta_eve_pct_cet1")).toBe("Delta EVE pct CET1");
    expect(humanize("var")).toBe("VAR");
    expect(formatParam(true)).toBe("yes");
    expect(formatParam(0.99)).toBe("0.99");
    expect(formatParam(null)).toBe("none");
  });
});

describe("rating rules (port of contract/rules.py)", () => {
  it("rates inherent and residual", () => {
    expect(inherentRating(1, 4)).toBe("low");
    expect(inherentRating(3, 3)).toBe("medium");
    expect(inherentRating(3, 5)).toBe("high");
    expect(inherentRating(4, 4)).toBe("critical");
    expect(residualRating("high", "weak")).toBe("high");
    expect(residualRating("high", "adequate")).toBe("medium");
    expect(residualRating("medium", "strong")).toBe("low");
    expect(rate(5, 5, "strong")).toEqual(["critical", "medium"]);
    expect(overallRating(["low", "high", "medium"])).toBe("high");
    expect(overallRating([])).toBe("low");
    expect(() => inherentRating(0, 3)).toThrow();
  });
});

describe("variation count preview", () => {
  const questions = D.arrayOf(D.QuestionInfo)(questionsJson);
  const models = D.arrayOf(D.ModelSpec)(modelsJson);
  const spec = (id: string) => models.find((m) => m.model_id === id)!;
  const specs = Object.fromEntries(models.map((m) => [m.model_id, m]));

  it("counts the cartesian product and collapses inapplicable parameters", () => {
    const q1 = questions[0].default_plan;
    expect(cartesianCount(q1.grid.dimensions)).toBe(24);
    // covariance only applies to normal, student_t and montecarlo: 3x2x2 + 3x2 = 18
    expect(effectiveGridCount(spec("q1.var"), q1)).toBe(18);
    const q2 = questions[1].default_plan;
    expect(effectiveGridCount(spec("q2.resilience"), q2)).toBe(32);
    expect(planProblems(spec("q1.var"), q1, specs)).toEqual([]);
  });

  it("reports out-of-range values and empty dimensions", () => {
    const q1 = structuredClone(questions[0].default_plan);
    q1.grid.fixed.confidence = 1.5;
    q1.grid.dimensions.window_days = [];
    const problems = planProblems(spec("q1.var"), q1, specs);
    expect(problems.join("\n")).toMatch(/confidence must be at most 0.999/);
    expect(problems.join("\n")).toMatch(/at least one value for window_days/);
  });
});

describe("safe markdown", () => {
  it("renders structure without injecting raw HTML", () => {
    const md = "# Title\n\nSome **bold** and `code` <img src=x onerror=alert(1)>\n\n- a\n- b\n\n| k | v |\n|---|---|\n| VaR | 5% |\n\n[bad](javascript:alert(1)) [ok](https://example.com)";
    const { container } = render(<Markdown source={md} />);
    expect(container.querySelector("h2")?.textContent).toBe("Title");
    expect(container.querySelector("strong")?.textContent).toBe("bold");
    expect(container.querySelector("img")).toBeNull();
    expect(container.textContent).toContain("<img src=x onerror=alert(1)>");
    expect(container.querySelectorAll("li")).toHaveLength(2);
    expect(container.querySelector("td")?.textContent).toBe("VaR");
    const links = [...container.querySelectorAll("a")].map((a) => a.getAttribute("href"));
    expect(links).toEqual(["https://example.com"]);
  });
  it("allows only safe link targets", () => {
    expect(safeHref("javascript:alert(1)")).toBeNull();
    expect(safeHref("//evil.example")).toBeNull();
    expect(safeHref("/traces/x#y")).toBe("/traces/x#y");
    expect(safeHref("#step")).toBe("#step");
  });
});
