// Display copy for the five built-in checks.
//
// AssessmentResult carries check ids and sub-factor ids but not the registry's titles, so
// the viewer keeps a copy of the default descriptors, exactly as slicepoint_core/report.py
// does (it reads slicepoint_schemas.checks.DEFAULT_CHECK_REGISTRY). Titles and sub-factor
// titles below mirror that registry; "asks" and "means" mirror report.py `_ASKS` / `_MEANS`.
//
// A check that is not listed here still renders: its title and sub-factor names are the
// ids made readable, and it gets the generic "what this means" copy.
import type { CheckStatus } from "../contract/assessment-result.generated";
import { humanizeColumn } from "./labels";

export interface SubFactorCopy {
  readonly id: string;
  readonly title: string;
}

export interface CheckCopy {
  readonly id: string;
  readonly title: string;
  readonly definition: string;
  readonly asks: string;
  readonly subFactors: readonly SubFactorCopy[];
  readonly means: Readonly<Record<CheckStatus, string>>;
}

const sf = (id: string, title: string): SubFactorCopy => ({ id, title });

export const DEFAULT_CHECKS: readonly CheckCopy[] = [
  {
    id: "repeats",
    title: "Different people",
    definition:
      "Scans per distinct person: guards against repeat scans and patient leakage inflating accuracy.",
    asks: "Does each scan come from a different person, so the numbers are not inflated by repeats?",
    subFactors: [sf("scans", "Scans"), sf("people", "People"), sf("leakage", "Random vs by-person split leakage")],
    means: {
      ok: "Repeat scans are rare, so the sample size is close to what it looks like.",
      watch: "Some people were scanned more than once; read the accuracy numbers as somewhat optimistic.",
      problem:
        "Many scans come from the same people, so the sample is smaller than it looks and accuracy is likely " +
        "overstated. Use the effective n and remove repeats before relying on the accuracy numbers.",
    },
  },
  {
    id: "scanning",
    title: "Scan settings match",
    definition: "Similarity of the acquisition mix to the reference.",
    asks: "Do your scanners and scan settings look like the ones the model was checked on?",
    subFactors: [
      sf("scanner_vendor", "Scanner"),
      sf("contrast_phase", "Contrast"),
      sf("slice_thickness_class", "Slice thickness"),
      sf("domain_auc", "Scans distinguishable from the reference (domain AUC)"),
      sf("coverage", "Scans outside the reference's coverage"),
      sf("hu_shift", "Aorta brightness (HU) shift"),
      sf("kvp_shift", "Tube voltage (kVp) shift"),
      sf("impossible_values", "Impossible values (diameter, HU, kVp, slice, organ volume)"),
      sf("embedding_shortcuts", "Embeddings encode scanner/protocol more than the aneurysm"),
    ],
    means: {
      ok: "Your scans look like the reference scans, so the model sees familiar images.",
      watch:
        "Some scan settings differ from the reference; check the named settings before relying on the model for " +
        "those scans.",
      problem:
        "Your scans differ clearly from what the model was checked on, so it may perform worse here than its " +
        "published results.",
    },
  },
  {
    id: "patients",
    title: "Patients match",
    definition: "Similarity of the patient mix to the reference.",
    asks: "Do your patients (sex, age, aneurysm size) look like the reference patients?",
    subFactors: [
      sf("sex", "Sex"),
      sf("age_band", "Age"),
      sf("aaa_size_class", "AAA size class"),
      sf("labelled_diameter_shift", "Labelled aorta diameter distribution shift"),
      sf("predicted_diameter_shift", "Model-measured aorta diameter distribution shift"),
    ],
    means: {
      ok: "Your patient mix is close to the reference.",
      watch:
        "Your patient mix differs somewhat from the reference; results for the named groups carry more uncertainty.",
      problem:
        "Your patients differ clearly from the reference; the model's published accuracy may not hold for them.",
    },
  },
  {
    id: "labels",
    title: "Labels follow 30 mm rule",
    definition: "Share of labels consistent with the AAA decision line.",
    asks: "Do your aneurysm labels follow the same decision line as the reference?",
    subFactors: [
      sf("rule_conflicts", "Labels disagreeing with the decision line"),
      sf("cutoff_alignment", "Cutoff alignment with reference"),
    ],
    means: {
      ok: "Your labels follow the decision line, so accuracy is measured against a consistent standard.",
      watch: "Some labels disagree with the decision line; the accuracy numbers may be slightly off.",
      problem:
        "Your labels do not follow the decision line consistently. Review the labelling before trusting any " +
        "accuracy number in this report.",
    },
  },
  {
    id: "accuracy",
    title: "AI accuracy",
    definition: "Composite of segmentation Dice, size within tolerance and aneurysms caught.",
    asks: "Does the model find aneurysms and measure the aorta well on your scans?",
    subFactors: [
      sf("dice", "Outline quality (Dice)"),
      sf("size_within_tolerance", "Size within tolerance"),
      sf("aneurysms_caught", "Aneurysms caught"),
      sf("no_answers", "Model gave no answer"),
      sf("specificity", "False alarms (specificity)"),
      sf("subgroups", "Problems in subgroups"),
    ],
    means: {
      ok: "The model performed acceptably on your sample.",
      watch: "The model has weak spots on your data; review the named items and the cases list.",
      problem:
        "The model missed its targets on your data. Do not turn it on without a plan for the named problems.",
    },
  },
];

export const GENERIC_MEANS: Readonly<Record<CheckStatus, string>> = {
  ok: "Nothing in this check stands in the way.",
  watch: "This check needs a closer look before deciding.",
  problem: "This check found a problem that should be resolved before turning the model on.",
};

export const MEANS_NOT_RUN =
  "This check did not run, so it cannot support a GO. Supply the missing input and run the assessment again.";

const BY_ID: ReadonlyMap<string, CheckCopy> = new Map(DEFAULT_CHECKS.map((c) => [c.id, c]));

export function checkCopy(id: string): CheckCopy | undefined {
  return BY_ID.get(id);
}

export function checkTitle(id: string): string {
  return BY_ID.get(id)?.title ?? humanizeColumn(id);
}

export function subFactorTitle(checkId: string, subId: string): string {
  return BY_ID.get(checkId)?.subFactors.find((s) => s.id === subId)?.title ?? humanizeColumn(subId);
}
