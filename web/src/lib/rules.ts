/**
 * Port of `riskbot/contract/rules.py` so the UI previews the same ratings the server will compute.
 * The server remains authoritative: previews are labelled as such.
 */
import type { ControlStrength, Rating } from "../api/types";
import { RATINGS } from "../api/types";

/** Score = likelihood x impact (1-25): 1-4 low, 5-9 medium, 10-15 high, 16-25 critical. */
export function inherentRating(likelihood: number, impact: number): Rating {
  if (!(likelihood >= 1 && likelihood <= 5 && impact >= 1 && impact <= 5)) {
    throw new RangeError("likelihood and impact must be 1-5");
  }
  const score = likelihood * impact;
  if (score <= 4) return "low";
  if (score <= 9) return "medium";
  if (score <= 15) return "high";
  return "critical";
}

/** Weak controls leave the rating unchanged; adequate lowers it one level; strong lowers it two. */
export function residualRating(inherent: Rating, control: ControlStrength): Rating {
  const steps = { weak: 0, adequate: 1, strong: 2 }[control];
  return RATINGS[Math.max(0, RATINGS.indexOf(inherent) - steps)];
}

export function rate(likelihood: number, impact: number, control: ControlStrength): [Rating, Rating] {
  const inh = inherentRating(likelihood, impact);
  return [inh, residualRating(inh, control)];
}

/** Overall = the worst residual rating (low if there are no factors). */
export function overallRating(residuals: Rating[]): Rating {
  return residuals.reduce<Rating>((worst, r) => (RATINGS.indexOf(r) > RATINGS.indexOf(worst) ? r : worst), "low");
}
