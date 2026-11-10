// Notes, methods and limits, the thresholds the run used, and provenance. The copy follows
// report.py `_methods_section` / `_provenance_section`; every number comes from the result.
import type { AssessmentResult, ThresholdProfile } from "../contract";
import { SCHEMA_VERSION } from "../contract";
import { formatTimestamp, num } from "./format";
import { displaySiteName, readable } from "./labels";
import { checkLookup, type CheckLookup } from "./registry";
import { NOT_RECORDED, STEP, type StatusLabel } from "./status";

export interface KeyValue {
  readonly label: string;
  readonly value: string;
  /** Machine value (id, hash) worth showing in a monospace font. */
  readonly code?: boolean;
}

export interface TriggerRow {
  readonly name: string;
  readonly yellow: string;
  readonly red: string;
  readonly worse: string;
  readonly kind: string;
  readonly inclusive: string;
}

export type ThresholdsView =
  | { readonly kind: "not_recorded"; readonly message: string }
  | {
      readonly kind: "ok";
      readonly profile: readonly KeyValue[];
      readonly rules: readonly KeyValue[];
      readonly targets: readonly KeyValue[];
      readonly triggers: readonly TriggerRow[];
      readonly parameters: readonly KeyValue[];
      readonly sources: readonly KeyValue[];
    };

export interface StepView {
  readonly step: string;
  readonly status: StatusLabel;
  readonly detail: string;
}

export interface AboutView {
  readonly notes: readonly string[];
  readonly methods: readonly string[];
  readonly limits: readonly string[];
  readonly thresholds: ThresholdsView;
  readonly provenance: readonly KeyValue[];
  readonly steps: readonly StepView[];
  readonly stepsLine: string;
  /** How the viewer read the file, when it had to interpret something (shown in provenance). */
  readonly readNotes: readonly string[];
}

/** Entries of a schema map (whose generated type allows undefined values), without the holes. */
function defined<T>(m: Record<string, T | undefined> | null | undefined): [string, T][] {
  return Object.entries(m ?? {}).flatMap(([k, v]) => (v === undefined ? [] : [[k, v] as [string, T]]));
}

function thresholdsView(t: ThresholdProfile | null | undefined, lookup: CheckLookup): ThresholdsView {
  if (t === null || t === undefined) {
    return {
      kind: "not_recorded",
      message:
        `The threshold values were ${NOT_RECORDED} (written before slicepoint-core 0.2.0). ` +
        "The viewer shows them as not recorded and assumes none.",
    };
  }
  const p = t.provenance;
  const rules: KeyValue[] = [];
  if (t.aaa) {
    rules.push(
      { label: "AAA decision line", value: `${t.aaa.decision_line_mm} mm (AAA if max diameter ≥ this)` },
      { label: "Large aneurysm line", value: `${t.aaa.large_aneurysm_line_mm} mm` },
      { label: "Near the decision line", value: `± ${t.aaa.nearby_window_mm} mm` },
      { label: "Size tolerance", value: `${t.aaa.size_tolerance_mm} mm` },
      { label: "Agreement (Bland-Altman) tolerance", value: `${t.aaa.bland_altman_tolerance_mm} mm` },
    );
  } else {
    rules.push({ label: "AAA rules", value: NOT_RECORDED });
  }
  rules.push(
    {
      label: "Dice markers",
      value: t.dice_markers ? `${t.dice_markers.lower} (basic), ${t.dice_markers.upper} (clinical)` : NOT_RECORDED,
    },
    { label: "Minimum group size", value: `${t.min_group_size} scans` },
  );
  return {
    kind: "ok",
    profile: [
      { label: "Profile", value: t.profile_id, code: true },
      { label: "Model", value: t.model_id, code: true },
      { label: "Site", value: t.site_id ?? "any site" },
      { label: "Source", value: p.source },
      { label: "Author", value: p.author },
      { label: "Date", value: p.date },
      ...(p.notes ? [{ label: "Notes", value: p.notes }] : []),
    ],
    rules,
    targets: defined(t.check_targets).map(([id, v]) => ({ label: lookup.title(id), value: `${v} of 100` })),
    triggers: defined(t.triggers).map(([name, tr]) => ({
      name,
      yellow: tr.yellow === null || tr.yellow === undefined ? "–" : num(tr.yellow),
      red: tr.red === null || tr.red === undefined ? "–" : num(tr.red),
      worse: tr.worse === "high" ? "higher is worse" : "lower is worse",
      kind: tr.kind ?? "",
      inclusive: tr.inclusive ? "yes" : "no",
    })),
    parameters: defined(t.parameters).map(([k, v]) => ({ label: k, value: num(v), code: true })),
    sources: defined(t.value_sources).map(([k, v]) => ({ label: k, value: v, code: true })),
  };
}

export function buildAbout(result: AssessmentResult, readNotes: readonly string[] = []): AboutView {
  const t = result.thresholds ?? null;
  const st = result.strata ?? null;
  const ref = result.reference;
  const decisionLine = t?.aaa ? `${t.aaa.decision_line_mm} mm` : `decision line ${NOT_RECORDED}`;
  const icc = t?.parameters?.repeat_scan_icc;
  const methods = [
    "The reference standard is your hospital's own labels and measurements, not an independent read.",
    "Primary sensitivity and specificity count a missing AI answer as wrong; the secondary “when answered” pair " +
      "leaves those scans out.",
    "All ranges for proportions are 95% Wilson score intervals.",
    "Agreement uses AI minus label; the standard deviation divides by n (population SD).",
    st
      ? `Groups with fewer than ${st.min_group_size} scans are shown as “Too few”; sensitivity needs at least ` +
        `${st.min_aaa_for_sensitivity} aneurysms. These rules count scans, not people.`
      : `By-group suppression rules: ${NOT_RECORDED}.`,
    `Effective n is Kish's design-effect sample size over real people${icc !== undefined ? ` (ICC ${num(icc)})` : ""}: ` +
      "repeat scans of one person carry less information than scans of different people.",
  ];
  const limits = [
    `The reference is “${ref.reference_id}”, built from site “${ref.site_id}” (${ref.n_cases} cases). A fit check is ` +
      "only as good as its reference; ask the vendor for the model's own training or validation distribution.",
    "The verdict rule is status-based: any Problem gives NO-GO, any Watch or check not run gives BORDERLINE, " +
      "otherwise GO. It was inferred from the proof-of-concept and is pending ratification.",
    `The label rule (${decisionLine}) is specific to abdominal aortic aneurysm; the other checks apply to imaging AI generally.`,
    "Input today is a curated set of four parquet files. Readers for raw DICOM or PACS exports are not built yet.",
    "This is a sample, not a trial: wide intervals mean the data cannot settle the question either way.",
    "0 to 100 check scores exist only as an unvalidated draft. They are hidden unless the file carries them and you switch them on.",
  ];
  const site = displaySiteName(result.site_id, result.site_name);
  const provenance: KeyValue[] = [
    { label: "Site", value: site === result.site_id ? site : `${site} (site id ${result.site_id})` },
    { label: "Reference profile", value: `${ref.reference_id} (site ${ref.site_id}, ${ref.n_cases} cases)` },
    { label: "Reference fingerprint", value: ref.fingerprint ?? "n/a", code: true },
    { label: "Threshold profile", value: result.profile_id, code: true },
    { label: "Model", value: result.model_id, code: true },
    { label: "Embedding space", value: result.embedding_space_id ?? "none", code: true },
    { label: "Dataset fingerprint", value: result.dataset_fingerprint ?? "n/a", code: true },
    { label: "Schema version", value: result.schema_version ?? SCHEMA_VERSION },
    { label: "Generated at", value: `${formatTimestamp(result.generated_at)} (${result.generated_at})` },
    { label: "Generated by", value: result.generator },
    { label: "Shown by", value: `SlicePoint viewer (reads schema ${SCHEMA_VERSION}); nothing was recomputed` },
    { label: "Verdict rule", value: result.verdict.rationale },
  ];
  const steps = result.steps.map((s) => ({ step: s.step, status: STEP[s.state], detail: s.detail ?? "" }));
  const nSkip = result.steps.filter((s) => s.state === "skipped").length;
  const nFail = result.steps.filter((s) => s.state === "failed").length;
  return {
    notes: (result.notes ?? []).map(readable),
    methods,
    limits,
    thresholds: thresholdsView(t, checkLookup(result.check_descriptors)),
    provenance,
    steps,
    stepsLine: `${steps.length} steps: ${nSkip} skipped, ${nFail} failed. A skipped step never counts as passed.`,
    readNotes,
  };
}
