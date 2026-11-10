// Performance on the site's sample, as recorded in the result. Nothing is recomputed.
import type { BinMetricsV0, PerformanceSummary, ThresholdProfile } from "../contract";
import { NA, mm, num, pct } from "./format";
import { NOT_RECORDED } from "./status";

export interface CiPoint {
  readonly label: string;
  readonly point: number | null;
  readonly lo: number | null;
  readonly hi: number | null;
}

export interface BinaryView {
  readonly lead: string;
  readonly rows: readonly { readonly measure: string; readonly primary: string; readonly answered: string }[];
  readonly chart: readonly CiPoint[];
}

export interface ToleranceBar {
  readonly label: string;
  readonly share: number | null;
  readonly display: string;
}

export type DiameterView =
  | { readonly kind: "missing"; readonly message: string }
  | { readonly kind: "too_few"; readonly message: string }
  | { readonly kind: "ok"; readonly rows: readonly { label: string; value: string }[]; readonly bars: readonly ToleranceBar[] };

export type DiceView =
  | { readonly kind: "missing"; readonly message: string }
  | {
      readonly kind: "ok";
      readonly median: number;
      readonly mean: number;
      readonly text: string;
      readonly markers: { readonly lower: number; readonly upper: number } | null;
      readonly markersNote: string | null;
    };

export interface PerformanceView {
  readonly binary: BinaryView | { readonly kind: "missing"; readonly message: string };
  readonly diameter: DiameterView;
  readonly dice: DiceView;
}

function ci(m: BinMetricsV0, which: "sens" | "spec"): string {
  const [p, lo, hi, k, n] =
    which === "sens" ? [m.sens, m.sens_lo, m.sens_hi, m.tp, m.n_aaa] : [m.spec, m.spec_lo, m.spec_hi, m.tn, m.n_not_aaa];
  if (p === null || p === undefined) return `${NA} (none in sample)`;
  return `${pct(p)} (${k}/${n}); 95% CI ${pct(lo)} to ${pct(hi)}`;
}

const ROLE_NAME: Readonly<Record<string, string>> = { bland_altman: "agreement tolerance", size: "size tolerance" };

export function buildPerformance(perf: PerformanceSummary, thresholds: ThresholdProfile | null | undefined): PerformanceView {
  const wrong = perf.aaa_missing_as_wrong ?? null;
  const answered = perf.aaa_when_answered ?? null;
  const binary =
    wrong === null || answered === null
      ? { kind: "missing" as const, message: "Not evaluated: needs both labels and model predictions." }
      : {
          lead:
            `The primary numbers count a missing AI answer as wrong. The "when answered" numbers leave out the ` +
            `${wrong.n_no_answer} scan${wrong.n_no_answer === 1 ? "" : "s"} with no answer. Ranges are 95% Wilson intervals.`,
          rows: [
            { measure: "Sensitivity (aneurysms caught)", primary: ci(wrong, "sens"), answered: ci(answered, "sens") },
            { measure: "Specificity (normals called normal)", primary: ci(wrong, "spec"), answered: ci(answered, "spec") },
            { measure: "Balanced accuracy", primary: pct(wrong.bal_acc), answered: pct(answered.bal_acc) },
            { measure: "G-mean", primary: num(wrong.g_mean), answered: num(answered.g_mean) },
            {
              measure: "Scans",
              primary: `${wrong.n} (${wrong.n_aaa} aneurysm, ${wrong.n_not_aaa} not; ${wrong.n_no_answer} no answer)`,
              answered: String(answered.n),
            },
          ],
          chart: [
            { label: "Sensitivity, primary", point: wrong.sens ?? null, lo: wrong.sens_lo ?? null, hi: wrong.sens_hi ?? null },
            { label: "Sensitivity, when answered", point: answered.sens ?? null, lo: answered.sens_lo ?? null, hi: answered.sens_hi ?? null },
            { label: "Specificity, primary", point: wrong.spec ?? null, lo: wrong.spec_lo ?? null, hi: wrong.spec_hi ?? null },
            { label: "Specificity, when answered", point: answered.spec ?? null, lo: answered.spec_lo ?? null, hi: answered.spec_hi ?? null },
          ],
        };

  const dm = perf.diameter ?? null;
  let diameter: DiameterView;
  if (dm === null) {
    diameter = { kind: "missing", message: "Not evaluated: needs labelled and predicted diameters." };
  } else if (dm.mae === null || dm.mae === undefined) {
    diameter = { kind: "too_few", message: `Too few paired measurements (${dm.n}; at least ${dm.min_n ?? 3} needed).` };
  } else {
    diameter = {
      kind: "ok",
      rows: [
        { label: "Pairs", value: String(dm.n) },
        { label: "Average difference (bias)", value: mm(dm.bias, 2, true) },
        {
          label: "95% limits of agreement",
          value: `${mm(dm.loa_low, 1, true)} to ${mm(dm.loa_high, 1, true)} (bias ± 1.96 × population SD ${mm(dm.sd, 2)})`,
        },
        { label: "Mean absolute error", value: `${mm(dm.mae, 2)} (RMSE ${mm(dm.rmse, 2)})` },
        { label: "Spearman correlation", value: num(dm.spearman) },
      ],
      bars: [...dm.within_tolerance]
        .sort((a, b) => a.tolerance_mm - b.tolerance_mm)
        .map((w) => ({
          label: `Within ${w.tolerance_mm} mm (${ROLE_NAME[w.role] ?? w.role} from the profile)`,
          share: w.share ?? null,
          display: pct(w.share),
        })),
    };
  }

  const d = perf.dice ?? null;
  const markers = thresholds?.dice_markers ?? null;
  const dice: DiceView =
    d === null
      ? { kind: "missing", message: "Not evaluated: no Dice values in the predictions." }
      : {
          kind: "ok",
          median: d.median,
          mean: d.mean,
          text:
            `Median ${d.median.toFixed(3)}, mean ${d.mean.toFixed(3)}; ${pct(d["share_below_0.90"])} of scans below 0.90 ` +
            `and ${pct(d["share_below_0.85"])} below 0.85.`,
          markers: markers ? { lower: markers.lower, upper: markers.upper } : null,
          markersNote: markers ? null : `Dice markers ${NOT_RECORDED}.`,
        };
  return { binary, diameter, dice };
}
