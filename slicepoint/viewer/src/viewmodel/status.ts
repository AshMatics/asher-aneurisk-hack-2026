// Status labels. Colour is never the only signal: every tone has a text label and a glyph.
import type { CheckStatus, StepState, VerdictOutcome } from "../contract";

export type Tone = "ok" | "watch" | "problem" | "skip";

export interface StatusLabel {
  readonly tone: Tone;
  /** Text that carries the status on its own, e.g. "Problem". */
  readonly label: string;
  /** Decorative glyph, hidden from assistive technology. */
  readonly glyph: string;
}

export const CHECK_STATUS: Readonly<Record<CheckStatus, StatusLabel>> = {
  ok: { tone: "ok", label: "OK", glyph: "✓" },
  watch: { tone: "watch", label: "Watch", glyph: "!" },
  problem: { tone: "problem", label: "Problem", glyph: "✕" },
};

export const NOT_EVALUATED: StatusLabel = { tone: "skip", label: "Not evaluated", glyph: "–" };
export const FAILED: StatusLabel = { tone: "problem", label: "Failed", glyph: "✕" };

export const VERDICT: Readonly<Record<VerdictOutcome, StatusLabel>> = {
  go: { tone: "ok", label: "GO", glyph: "✓" },
  no_go: { tone: "problem", label: "NO-GO", glyph: "✕" },
  borderline: { tone: "watch", label: "BORDERLINE", glyph: "!" },
};

export const STEP: Readonly<Record<StepState, StatusLabel>> = {
  ok: { tone: "ok", label: "Ran", glyph: "✓" },
  skipped: { tone: "skip", label: "Skipped", glyph: "–" },
  failed: { tone: "problem", label: "Failed", glyph: "✕" },
};

/** Notebook severities in evidence values (report.py `_SEVERITY_STATUS`). */
export const SEVERITY_STATUS: Readonly<Record<string, CheckStatus>> = { red: "problem", yellow: "watch", ok: "ok" };

export const NOT_RECORDED = "not recorded in this result";

export const DISCLAIMER =
  "Results come from a test sample, not a full trial. This report supports a decision and is not medical advice.";
