/** The dataset chosen on the home screen, handed to the plan editor. */
import { createContext, useContext, useState, type ReactNode } from "react";
import type { DataQualityFinding, Dataset, QuestionId } from "../api/types";

export interface Draft {
  question: QuestionId;
  dataset: Dataset;
  source: "sample" | "upload";
  fileName?: string;
  findings: DataQualityFinding[];
}

const DraftContext = createContext<{ draft: Draft | null; setDraft: (d: Draft | null) => void } | null>(null);

export function DraftProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState<Draft | null>(null);
  return <DraftContext.Provider value={{ draft, setDraft }}>{children}</DraftContext.Provider>;
}

export function useDraft() {
  const ctx = useContext(DraftContext);
  if (!ctx) throw new Error("useDraft must be used inside <DraftProvider>");
  return ctx;
}

export function datasetSummary(ds: Dataset): string {
  switch (ds.kind) {
    case "market":
      return `${ds.positions.length} positions · ${ds.dates.length} trading days · ${ds.base_currency}`;
    case "balance_sheet":
      return `${ds.assets.length} assets · ${ds.loan_pools.length} loan pools · ${ds.deposits.length} deposit segments · ${ds.currency}`;
    case "climate":
      return `${ds.holdings.length} holdings · ${new Set(ds.holdings.map((h) => h.sector)).size} sectors · ${ds.currency}`;
  }
}

export function datasetCurrency(ds: Dataset | undefined): string | undefined {
  if (!ds) return undefined;
  return ds.kind === "market" ? ds.base_currency : ds.currency;
}
