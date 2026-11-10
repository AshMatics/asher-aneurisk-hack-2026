// The verdict panel: derived outcome, and when a human override exists, the final outcome
// with who, when and why. The sentence follows report.py `_verdict_section`.
import type { AssessmentResult, VerdictOutcome } from "../contract";
import { formatTimestamp, joinAnd } from "./format";
import { checkTitle } from "./registry";
import { DISCLAIMER, VERDICT, type StatusLabel } from "./status";

export interface OverrideView {
  readonly derived: StatusLabel;
  readonly final: StatusLabel;
  readonly by: string;
  readonly at: string;
  readonly atIso: string;
  readonly note: string;
}

export interface VerdictView {
  readonly derivedOutcome: VerdictOutcome;
  readonly finalOutcome: VerdictOutcome;
  /** The outcome to act on: the override's when present, else the derived one. */
  readonly final: StatusLabel;
  readonly derived: StatusLabel;
  /** Plain-language sentence about what the checks found (the derived outcome). */
  readonly sentence: string;
  readonly counts: { readonly problem: number; readonly watch: number; readonly ok: number; readonly notEvaluated: number };
  readonly problems: readonly { id: string; title: string }[];
  readonly watches: readonly { id: string; title: string }[];
  readonly notEvaluated: readonly { id: string; title: string }[];
  readonly override: OverrideView | null;
  /** The producer's machine rationale (shown in provenance). */
  readonly rationale: string;
  readonly disclaimer: string;
}

export function buildVerdict(result: AssessmentResult): VerdictView {
  const v = result.verdict;
  const ref = (id: string) => ({ id, title: checkTitle(id) });
  const problems = v.results.filter((r) => r.status === "problem").map((r) => ref(r.check_id));
  const watches = v.results.filter((r) => r.status === "watch").map((r) => ref(r.check_id));
  const notEval = (v.not_evaluated ?? []).map(ref);
  const total = result.checks.length;
  let sentence: string;
  if (v.outcome === "no_go") {
    sentence =
      `${problems.length} of ${total} checks found a problem (${problems.map((p) => p.title).join(", ")}), so this AI ` +
      "should not be turned on for these patients and scanners until those are resolved.";
  } else if (v.outcome === "borderline") {
    const bits: string[] = [];
    if (watches.length) bits.push(`${watches.map((w) => w.title).join(", ")} need${watches.length === 1 ? "s" : ""} a closer look`);
    if (notEval.length) bits.push(`${notEval.map((n) => n.title).join(", ")} could not be evaluated`);
    sentence = `No check found a clear problem, but ${bits.length ? joinAnd(bits) : "the result is not a clear pass"}, so decide only after a review.`;
  } else {
    sentence = `All ${total} checks passed on this sample, so the AI looks like a fit for these patients and scanners.`;
  }
  const o = v.override ?? null;
  const finalOutcome = o ? o.outcome : v.outcome;
  return {
    derivedOutcome: v.outcome,
    finalOutcome,
    final: VERDICT[finalOutcome],
    derived: VERDICT[v.outcome],
    sentence,
    counts: {
      problem: v.results.filter((r) => r.status === "problem").length,
      watch: v.results.filter((r) => r.status === "watch").length,
      ok: v.results.filter((r) => r.status === "ok").length,
      notEvaluated: result.checks.filter((c) => c.state !== "evaluated").length,
    },
    problems,
    watches,
    notEvaluated: notEval,
    override: o
      ? { derived: VERDICT[v.outcome], final: VERDICT[o.outcome], by: o.by, at: formatTimestamp(o.at), atIso: o.at, note: o.note }
      : null,
    rationale: v.rationale,
    disclaimer: DISCLAIMER,
  };
}
