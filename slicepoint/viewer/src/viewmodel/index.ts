// View-models: plain TypeScript that turns an AssessmentResult into display data.
// No React (enforced by eslint), so a Vue shell can reuse them (ADR 0001 §7).
// They compute no statistics; they only select, label and format what the result holds.
import type { AssessmentResult } from "../contract";
import { buildAbout, type AboutView } from "./about";
import { buildCases, type CasesView } from "./cases";
import { buildCheckCards, hasProvisionalScores, scoreMethods, type CheckCard } from "./checks";
import { formatTimestamp } from "./format";
import { displaySiteName } from "./labels";
import { buildPerformance, type PerformanceView } from "./performance";
import { buildStrata, type StrataView } from "./strata";
import { buildVerdict, type VerdictView } from "./verdict";

export interface ViewOptions {
  /** Show provisional scores. Ignored unless the file carries them. */
  readonly showScores: boolean;
  /** Notes from loading the file (see load.ts). */
  readonly readNotes?: readonly string[];
}

export interface HeaderView {
  readonly site: string;
  readonly siteId: string;
  readonly subtitle: string;
  readonly generated: string;
}

export interface ScoresView {
  /** The file carries provisional scores, so the toggle may be offered. */
  readonly available: boolean;
  /** Scores are being shown (available and switched on). */
  readonly shown: boolean;
  readonly methods: readonly string[];
}

export interface ResultView {
  readonly header: HeaderView;
  readonly verdict: VerdictView;
  readonly checks: readonly CheckCard[];
  readonly scores: ScoresView;
  readonly performance: PerformanceView;
  readonly strata: StrataView;
  readonly cases: CasesView;
  readonly about: AboutView;
}

export function buildViewModel(result: AssessmentResult, opts: ViewOptions): ResultView {
  const available = hasProvisionalScores(result);
  const shown = available && opts.showScores;
  const site = displaySiteName(result.site_id, result.site_name);
  return {
    header: {
      site,
      siteId: result.site_id,
      subtitle:
        `Compared with reference ${result.reference.reference_id} (site ${result.reference.site_id}) ` +
        `for model ${result.model_id}, threshold profile ${result.profile_id}.`,
      generated: formatTimestamp(result.generated_at),
    },
    verdict: buildVerdict(result),
    checks: buildCheckCards(result, { showScores: shown }),
    scores: { available, shown, methods: available ? scoreMethods(result) : [] },
    performance: buildPerformance(result.performance, result.thresholds),
    strata: buildStrata(result.strata),
    cases: buildCases(result.cases_to_review),
    about: buildAbout(result, opts.readNotes ?? []),
  };
}

export * from "./about";
export * from "./cases";
export * from "./checks";
export * from "./format";
export * from "./labels";
export * from "./load";
export * from "./performance";
export * from "./registry";
export * from "./status";
export * from "./strata";
export * from "./verdict";
export type { AssessmentResult, ReviewReason } from "../contract";
export { SCHEMA_VERSION } from "../contract";
