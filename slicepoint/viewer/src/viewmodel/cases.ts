// Cases to review (result.cases_to_review), plus display-only sorting and filtering.
// The list, its reasons and priorities come from the result; the viewer only reorders
// and filters what is there.
import type { CasesToReview, ReviewCase, ReviewReason } from "../contract";
import { mm } from "./format";
import { NOT_RECORDED } from "./status";

export const REASON_LABEL: Readonly<Record<ReviewReason, string>> = {
  missed_aneurysm: "Missed aneurysm",
  no_answer_on_aneurysm: "No AI answer on a labelled aneurysm",
  no_answer: "No AI answer",
  size_error: "Size off",
  false_alarm: "False alarm",
};

export interface CaseRowView {
  readonly caseId: string;
  readonly personGroup: string;
  readonly priority: number;
  readonly reasons: readonly ReviewReason[];
  /** Each reason as a sentence; the size error carries its value and tolerance. */
  readonly why: readonly string[];
  readonly label: string;
  readonly aiCall: string;
  readonly labelSize: string;
  readonly aiSize: string;
  readonly difference: string;
  /** |error_mm|, for sorting; null when either diameter is missing. */
  readonly absErrorMm: number | null;
  /** Position in the file (most urgent first, as the producer ordered it). */
  readonly order: number;
}

export type CasesView =
  | { readonly kind: "not_recorded"; readonly message: string }
  | {
      readonly kind: "ok";
      readonly lead: string;
      readonly countLine: string;
      readonly rows: readonly CaseRowView[];
      readonly reasonsPresent: readonly { readonly code: ReviewReason; readonly label: string; readonly count: number }[];
    };

function yn(v: boolean | null | undefined): string {
  return v === null || v === undefined ? "no answer" : v ? "AAA" : "no AAA";
}

function reasonText(k: ReviewCase, r: ReviewReason, tol: number): string {
  if (r === "size_error" && k.error_mm !== null && k.error_mm !== undefined) {
    return `Size off by ${mm(k.error_mm, 1, true)} (tolerance ${tol} mm)`;
  }
  return REASON_LABEL[r];
}

export function buildCases(cr: CasesToReview | null | undefined): CasesView {
  if (cr === null || cr === undefined) return { kind: "not_recorded", message: `No cases-to-review list: ${NOT_RECORDED}.` };
  const tol = cr.size_tolerance_mm;
  const cases = cr.cases ?? [];
  const rows = cases.map(
    (k, i): CaseRowView => ({
      caseId: k.case_id,
      personGroup: k.person_group,
      priority: k.priority,
      reasons: k.reasons,
      why: k.reasons.map((r) => reasonText(k, r, tol)),
      label: k.aaa === null || k.aaa === undefined ? "n/a" : yn(k.aaa),
      aiCall: yn(k.ai_aaa),
      labelSize: mm(k.reference_diameter_mm),
      aiSize: mm(k.ai_diameter_mm),
      difference: mm(k.error_mm, 1, true),
      absErrorMm: k.error_mm === null || k.error_mm === undefined ? null : Math.abs(k.error_mm),
      order: i,
    }),
  );
  const counts = new Map<ReviewReason, number>();
  for (const k of cases) for (const r of k.reasons) counts.set(r, (counts.get(r) ?? 0) + 1);
  const reasonsPresent = (Object.keys(REASON_LABEL) as ReviewReason[])
    .filter((r) => counts.has(r))
    .map((code) => ({ code, label: REASON_LABEL[code], count: counts.get(code) ?? 0 }));
  return {
    kind: "ok",
    lead:
      "Scans where the AI missed an aneurysm, gave no answer, measured the aorta outside the " +
      `${tol} mm size tolerance, or raised a false alarm. Open these in your image viewer first.`,
    countLine: `${cases.length} of ${cr.n_scans} scans flagged.`,
    rows,
    reasonsPresent,
  };
}

export type CaseSortKey = "priority" | "error" | "case";
export type SortDir = "asc" | "desc";

export interface CaseFilter {
  readonly reason: ReviewReason | "all";
  /** Case-insensitive substring of the case id or person group. */
  readonly query: string;
}

export function filterCases(rows: readonly CaseRowView[], f: CaseFilter): CaseRowView[] {
  const q = f.query.trim().toLowerCase();
  return rows.filter(
    (r) =>
      (f.reason === "all" || r.reasons.includes(f.reason)) &&
      (!q || r.caseId.toLowerCase().includes(q) || r.personGroup.toLowerCase().includes(q)),
  );
}

/**
 * Sort for display. "priority" ascending is the file's own order (most urgent first).
 * Rows without a diameter error always sort last by "error".
 */
export function sortCases(rows: readonly CaseRowView[], key: CaseSortKey, dir: SortDir): CaseRowView[] {
  const sign = dir === "asc" ? 1 : -1;
  return [...rows].sort((a, b) => {
    if (key === "error") {
      if (a.absErrorMm === null || b.absErrorMm === null) {
        if (a.absErrorMm === b.absErrorMm) return a.order - b.order;
        return a.absErrorMm === null ? 1 : -1;
      }
      return sign * (a.absErrorMm - b.absErrorMm) || a.order - b.order;
    }
    if (key === "case") return sign * a.caseId.localeCompare(b.caseId);
    return sign * (a.priority - b.priority) || sign * (a.order - b.order);
  });
}
