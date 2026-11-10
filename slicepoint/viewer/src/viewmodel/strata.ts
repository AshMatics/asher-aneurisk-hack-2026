// The by-group table exactly as the result records it (result.strata). The suppression
// rules shown are the ones stored with the table; nothing is recomputed or defaulted.
import type { Strata } from "../contract";
import { mm, pct } from "./format";
import { displayLevel, humanizeColumn } from "./labels";
import { NOT_RECORDED } from "./status";

export interface StratumRowView {
  readonly level: string;
  readonly n: number;
  readonly people: number;
  readonly nAaa: number;
  readonly tooFew: boolean;
  /** "Too few (fewer than 15 scans)" when every metric is suppressed. */
  readonly tooFewText: string | null;
  readonly bias: string;
  readonly mae: string;
  readonly within: string;
  /** Sensitivity with its interval, or the suppression reason. */
  readonly sens: string;
  readonly sensSuppressed: boolean;
}

export interface StratumGroupView {
  readonly variable: string;
  readonly label: string;
  readonly rows: readonly StratumRowView[];
}

export type StrataView =
  | { readonly kind: "not_recorded"; readonly message: string }
  | {
      readonly kind: "ok";
      readonly lead: string;
      readonly toleranceMm: number;
      readonly minGroupSize: number;
      readonly groups: readonly StratumGroupView[];
    };

export function buildStrata(st: Strata | null | undefined): StrataView {
  if (st === null || st === undefined) return { kind: "not_recorded", message: `No by-group table: ${NOT_RECORDED}.` };
  const groups: StratumGroupView[] = [];
  for (const r of st.rows ?? []) {
    let g = groups.find((x) => x.variable === r.variable);
    if (!g) {
      g = { variable: r.variable, label: humanizeColumn(r.variable), rows: [] };
      groups.push(g);
    }
    const tooFewText = r.too_few ? `Too few (fewer than ${st.min_group_size} scans)` : null;
    let sens: string;
    if (r.too_few) sens = "";
    else if (r.sens_too_few) {
      sens = `Too few (${r.n_aaa === 0 ? "no aneurysms" : `${r.n_aaa} aneurysm${r.n_aaa === 1 ? "" : "s"}`})`;
    } else sens = `${pct(r.sens)} (${pct(r.sens_lo)} to ${pct(r.sens_hi)})`;
    (g.rows as StratumRowView[]).push({
      level: displayLevel(r.level),
      n: r.n,
      people: r.people,
      nAaa: r.n_aaa,
      tooFew: r.too_few,
      tooFewText,
      bias: r.too_few ? "" : mm(r.bias_mm, 2, true),
      mae: r.too_few ? "" : mm(r.mae_mm, 2),
      within: r.too_few ? "" : pct(r.within_tolerance),
      sens,
      sensSuppressed: r.sens_too_few,
    });
  }
  return {
    kind: "ok",
    lead:
      `Groups with fewer than ${st.min_group_size} scans show "Too few": their numbers would be noise. ` +
      `Sensitivity needs at least ${st.min_aaa_for_sensitivity} aneurysms in the group. Size tolerance ${st.size_tolerance_mm} mm.`,
    toleranceMm: st.size_tolerance_mm,
    minGroupSize: st.min_group_size,
    groups,
  };
}
