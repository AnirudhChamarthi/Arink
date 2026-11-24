/**
 * Unit-aware number formatting. Contract conventions (CONTRACT.md section 3): fractions are decimals
 * (0.07 = 7%), basis points are `bp`, currency is in the dataset's currency.
 */
import type { ParamValue, Unit } from "../api/types";

const LOCALE = "en-US";

function fixed(value: number, digits: number): string {
  return value.toLocaleString(LOCALE, { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function upTo(value: number, digits: number): string {
  return value.toLocaleString(LOCALE, { maximumFractionDigits: digits });
}

/** Digits so that small values keep two significant figures (e.g. 0.0004 -> 0.00040). */
function smartDigits(value: number, base: number): number {
  const abs = Math.abs(value);
  if (abs === 0 || abs >= 1) return base;
  const lead = Math.floor(-Math.log10(abs)); // zeros after the decimal point
  return Math.min(Math.max(base, lead + 2), 8);
}

export interface FormatOptions {
  /** ISO currency code for `currency` metrics; without it, values are grouped numbers with no symbol. */
  currency?: string;
  /** Show a sign for positive values (for signed deltas). */
  signed?: boolean;
}

export function formatValue(value: number | null | undefined, unit: Unit | null | undefined, opts: FormatOptions = {}): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  if (!Number.isFinite(value)) return value > 0 ? "∞" : "−∞";
  const sign = opts.signed && value > 0 ? "+" : "";
  let out: string;
  switch (unit) {
    case "fraction":
    case "fraction_of_gross": {
      const pct = value * 100;
      out = `${fixed(pct, smartDigits(pct, 2))}%`;
      break;
    }
    case "probability":
      out = fixed(value, smartDigits(value, 3));
      break;
    case "bp":
      out = `${upTo(value, Number.isInteger(value) ? 0 : 1)} bp`;
      break;
    case "currency": {
      const abs = Math.abs(value);
      const digits = abs >= 1000 ? 0 : smartDigits(value, 2);
      if (!opts.currency) {
        // Currency unknown (RunRecord does not carry it): grouped number, no symbol.
        out = fixed(value, digits);
        break;
      }
      try {
        out = value.toLocaleString(LOCALE, {
          style: "currency",
          currency: opts.currency,
          minimumFractionDigits: digits,
          maximumFractionDigits: digits,
        });
      } catch {
        out = `${fixed(value, digits)} ${opts.currency ?? ""}`.trim();
      }
      break;
    }
    case "count":
      out = Number.isInteger(value) ? upTo(value, 0) : fixed(value, smartDigits(value, 2));
      break;
    case "ratio":
      out = fixed(value, smartDigits(value, 2));
      break;
    case "tCO2e":
      out = `${upTo(value, Math.abs(value) >= 100 ? 0 : smartDigits(value, 2))} tCO₂e`;
      break;
    case "tCO2e_per_musd":
      out = `${fixed(value, smartDigits(value, 1))} tCO₂e/$m`;
      break;
    case "days":
      out = `${upTo(value, Number.isInteger(value) ? 0 : smartDigits(value, 1))} days`;
      break;
    case "years":
      out = `${fixed(value, smartDigits(value, 2))} yrs`;
      break;
    default:
      out = upTo(value, smartDigits(value, 4));
  }
  // Use a true minus sign for negatives (typographic, and screen readers read it as "minus").
  return sign + out.replace(/^-/, "−");
}

const UNIT_LABELS: Record<Unit, string> = {
  fraction_of_gross: "% of gross exposure",
  fraction: "%",
  currency: "currency",
  bp: "basis points",
  count: "count",
  ratio: "ratio",
  probability: "probability",
  tCO2e: "tCO₂e",
  tCO2e_per_musd: "tCO₂e per $m revenue",
  days: "days",
  years: "years",
};

export function unitLabel(unit: Unit | null | undefined, currency?: string): string {
  if (!unit) return "";
  if (unit === "currency" && currency) return currency;
  return UNIT_LABELS[unit] ?? unit;
}

/** "rate_shock_bp" -> "Rate shock bp"; keeps common finance acronyms upper-case. */
export function humanize(key: string): string {
  const acronyms = new Set(["var", "es", "eve", "nii", "lcr", "cet1", "rwa", "htm", "afs", "hqla", "waci", "evt", "fhs", "bp", "ci", "p05", "p95", "mv"]);
  const words = key.split(/[_\s]+/).filter(Boolean);
  return words
    .map((w, i) => (acronyms.has(w.toLowerCase()) ? w.toUpperCase() : i === 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(" ");
}

export function formatParam(value: ParamValue | undefined): string {
  if (value === undefined) return "—";
  if (value === null) return "none";
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (typeof value === "number") return upTo(value, 6);
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(LOCALE, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "UTC",
    timeZoneName: "short",
  });
}

export function shortHash(hash: string, n = 12): string {
  return hash.length > n ? `${hash.slice(0, n)}…` : hash;
}
