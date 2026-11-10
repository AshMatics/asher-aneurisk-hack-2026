// Check cards. Rendered generically from the result: one card per CheckRun, in the
// result's order. A check the viewer has no copy for still renders, with readable ids.
import type { AssessmentResult, CheckResult, CheckRun, EvidenceItem } from "../contract";
import { formatNEffective, int, num } from "./format";
import { humanizeEvidenceKey, readable } from "./labels";
import { GENERIC_MEANS, MEANS_NOT_RUN, checkCopy, checkTitle, subFactorTitle } from "./registry";
import { CHECK_STATUS, FAILED, NOT_EVALUATED, SEVERITY_STATUS, type StatusLabel } from "./status";

export interface Finding {
  readonly status: StatusLabel;
  readonly text: string;
}

export interface SubFactorView {
  readonly id: string;
  readonly title: string;
  readonly failing: boolean;
}

export interface EvidenceRow {
  readonly key: string;
  /** Short label: the part after the factor prefix, or the whole key. */
  readonly label: string;
  readonly value: string;
  readonly note?: string;
}

/** One finding (a factor the check evaluated) with the numbers behind it. */
export interface EvidenceGroup {
  readonly factor: string;
  readonly title: string;
  readonly status: StatusLabel;
  readonly text: string | null;
  readonly rows: readonly EvidenceRow[];
}

export interface ScoreView {
  readonly value: number;
  readonly display: string;
  readonly method: string;
  readonly target: number | null;
}

export interface CheckCard {
  readonly id: string;
  readonly title: string;
  /** False when the viewer has no copy for this check id (a custom check). */
  readonly known: boolean;
  readonly asks: string;
  readonly state: CheckRun["state"];
  readonly status: StatusLabel;
  /** For a skipped or failed check: why it did not run. */
  readonly reason: string | null;
  /** "Based on 80 scans from 40 people; effective n 32." */
  readonly nLine: string | null;
  readonly n: number | null;
  readonly nEffective: string | null;
  readonly nEffectiveMethod: string | null;
  readonly failing: readonly SubFactorView[];
  readonly subFactors: readonly SubFactorView[];
  /** Non-ok findings; the card's headline evidence. */
  readonly findings: readonly Finding[];
  /** Shown when there are no flagged findings: the check's summary or "Nothing to flag." */
  readonly summary: string | null;
  readonly means: string;
  /** Present only when provisional scores are switched on and the file carries one. */
  readonly score: ScoreView | null;
  readonly evidence: readonly EvidenceGroup[];
  readonly otherEvidence: readonly EvidenceRow[];
}

export function isScoreEvidence(key: string): boolean {
  return key === "score_basis" || key.startsWith("score_part.") || key.startsWith("score.");
}

function evidenceValue(ev: EvidenceItem): string {
  const v = ev.value;
  let text = typeof v === "string" ? readable(v) : num(v);
  if (ev.unit) text += ` ${ev.unit}`;
  return text;
}

function isFindingHead(ev: EvidenceItem): boolean {
  return !ev.key.includes(".") && typeof ev.value === "string" && ev.value in SEVERITY_STATUS;
}

function groupEvidence(
  checkId: string,
  res: CheckResult,
  showScores: boolean,
): { groups: EvidenceGroup[]; other: EvidenceRow[] } {
  const evidence = (res.evidence ?? []).filter(
    (ev) => (showScores || !isScoreEvidence(ev.key)) && ev.key !== "failing_factor_without_sub_factor",
  );
  const heads = new Map<string, { ev: EvidenceItem; rows: EvidenceRow[] }>();
  for (const ev of evidence) if (isFindingHead(ev)) heads.set(ev.key, { ev, rows: [] });
  const other: EvidenceRow[] = [];
  for (const ev of evidence) {
    if (isFindingHead(ev)) continue;
    const dot = ev.key.indexOf(".");
    const head = dot > 0 ? heads.get(ev.key.slice(0, dot)) : undefined;
    const row: EvidenceRow = {
      key: ev.key,
      label: humanizeEvidenceKey(head ? ev.key.slice(dot + 1) : ev.key),
      value: evidenceValue(ev),
      ...(ev.text && ev.key === "not_evaluated" ? { note: ev.text } : {}),
    };
    (head ? head.rows : other).push(row);
  }
  const groups = [...heads.entries()].map(([factor, { ev, rows }]) => ({
    factor,
    title: subFactorTitleOrFactor(checkId, factor),
    status: CHECK_STATUS[SEVERITY_STATUS[ev.value as string] ?? "ok"],
    text: ev.text ? readable(ev.text) : null,
    rows,
  }));
  return { groups, other };
}

function subFactorTitleOrFactor(checkId: string, factor: string): string {
  const copy = checkCopy(checkId);
  const sub = copy?.subFactors.find((s) => s.id === factor);
  return sub ? sub.title : subFactorTitle("", factor);
}

function findings(res: CheckResult): Finding[] {
  const out: Finding[] = [];
  for (const ev of res.evidence ?? []) {
    if (!isFindingHead(ev) || !ev.text) continue;
    out.push({ status: CHECK_STATUS[SEVERITY_STATUS[ev.value as string] ?? "ok"], text: readable(ev.text) });
  }
  return out;
}

function nLine(res: CheckResult): string {
  let line = `Based on ${int(res.n)} scans`;
  if (res.subjects !== null && res.subjects !== undefined) line += ` from ${int(res.subjects)} people`;
  if (res.n_effective !== null && res.n_effective !== undefined) line += `; effective n ${formatNEffective(res.n_effective)}`;
  return `${line}.`;
}

export interface CheckCardOptions {
  /** Show provisional scores (only honoured when the result carries them). */
  readonly showScores: boolean;
}

export function buildCheckCards(result: AssessmentResult, opts: CheckCardOptions): CheckCard[] {
  const results = new Map(result.verdict.results.map((r) => [r.check_id, r]));
  const targets = result.thresholds?.check_targets ?? {};
  return result.checks.map((run): CheckCard => {
    const id = run.check_id;
    const copy = checkCopy(id);
    const title = checkTitle(id);
    const asks = copy?.asks ?? "";
    const allSubs = (failingIds: readonly string[]): SubFactorView[] => {
      const known = (copy?.subFactors ?? []).map((s) => ({ id: s.id, title: s.title, failing: failingIds.includes(s.id) }));
      const extra = failingIds
        .filter((f) => !known.some((k) => k.id === f))
        .map((f) => ({ id: f, title: subFactorTitle(id, f), failing: true }));
      return [...known, ...extra];
    };
    const res = results.get(id);
    if (run.state !== "evaluated" || res === undefined) {
      const reason =
        run.reason ?? (run.state === "evaluated" ? "The check is marked evaluated but its result is missing from the verdict." : null);
      return {
        id,
        title,
        known: copy !== undefined,
        asks,
        state: run.state,
        status: run.state === "failed" ? FAILED : NOT_EVALUATED,
        reason,
        nLine: null,
        n: null,
        nEffective: null,
        nEffectiveMethod: null,
        failing: [],
        subFactors: allSubs([]),
        findings: [],
        summary: null,
        means: MEANS_NOT_RUN,
        score: null,
        evidence: [],
        otherEvidence: [],
      };
    }
    const failingIds = res.failing_sub_factors ?? [];
    const subs = allSubs(failingIds);
    const flagged = findings(res).filter((f) => f.status.tone !== "ok");
    const { groups, other } = groupEvidence(id, res, opts.showScores);
    const target = targets[id];
    const score =
      opts.showScores && res.score !== null && res.score !== undefined
        ? {
            value: res.score,
            display: res.score.toFixed(0),
            method: res.score_method ?? "unnamed method",
            target: target ?? null,
          }
        : null;
    return {
      id,
      title,
      known: copy !== undefined,
      asks,
      state: run.state,
      status: CHECK_STATUS[res.status],
      reason: null,
      nLine: nLine(res),
      n: res.n,
      nEffective: res.n_effective === null || res.n_effective === undefined ? null : formatNEffective(res.n_effective),
      nEffectiveMethod: res.n_effective_method ?? null,
      failing: subs.filter((s) => s.failing),
      subFactors: subs,
      findings: flagged,
      summary: flagged.length ? null : readable(res.summary ?? "Nothing to flag."),
      means: (copy?.means ?? GENERIC_MEANS)[res.status],
      score,
      evidence: groups,
      otherEvidence: other,
    };
  });
}

/** True when the file carries provisional 0-100 scores (written with --show-provisional-scores). */
export function hasProvisionalScores(result: AssessmentResult): boolean {
  return result.verdict.results.some((r) => r.score !== null && r.score !== undefined);
}

/** The score methods named in the file, e.g. ["provisional-v0"]. */
export function scoreMethods(result: AssessmentResult): string[] {
  return [
    ...new Set(
      result.verdict.results.flatMap((r) => (r.score !== null && r.score !== undefined && r.score_method ? [r.score_method] : [])),
    ),
  ];
}

export const PROVISIONAL_BANNER =
  "Provisional scores, not validated. The 0 to 100 scores use a draft formula that has not been ratified " +
  "(ADR 0001, open question 2) and must not drive a decision. The verdict uses check status only.";
