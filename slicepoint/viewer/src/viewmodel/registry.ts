// Display copy for the checks.
//
// Titles, definitions and sub-factor titles come from the result's own `check_descriptors`
// (written by slicepoint-core 0.2.1 and later), so a new check needs no viewer change. A file
// written before that has no descriptors; the viewer then falls back to DEFAULT_CHECKS, a copy
// of slicepoint_schemas.checks.DEFAULT_CHECK_REGISTRY. "asks" and "means" are viewer-only
// plain-language copy that mirrors report.py `_ASKS` / `_MEANS`; they stay here either way.
//
// A check with neither a descriptor nor a copy still renders: its title and sub-factor names
// are the ids made readable, and it gets the generic "what this means" copy.
import type { CheckDescriptor, CheckStatus } from "../contract/assessment-result.generated";
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

/** Looks up display copy for the checks of one result. */
export interface CheckLookup {
  /** Copy for a check: from the result's descriptor when present, else DEFAULT_CHECKS; undefined when neither knows it. */
  copy(id: string): CheckCopy | undefined;
  title(id: string): string;
  subFactorTitle(checkId: string, subId: string): string;
}

function fromDescriptor(d: CheckDescriptor): CheckCopy {
  const fallback = BY_ID.get(d.id);
  return {
    id: d.id,
    title: d.title,
    definition: d.definition,
    asks: fallback?.asks ?? d.definition,
    subFactors: (d.sub_factors ?? []).map((s) => sf(s.id, s.title)),
    means: fallback?.means ?? GENERIC_MEANS,
  };
}

/**
 * The lookup for a result: its `check_descriptors` win, DEFAULT_CHECKS fill in for a file
 * written without them (or a check id they do not cover, which the contract forbids).
 */
export function checkLookup(descriptors?: readonly CheckDescriptor[] | null): CheckLookup {
  const own = new Map((descriptors ?? []).map((d) => [d.id, fromDescriptor(d)]));
  const copy = (id: string) => own.get(id) ?? BY_ID.get(id);
  return {
    copy,
    title: (id) => copy(id)?.title ?? humanizeColumn(id),
    subFactorTitle: (checkId, subId) =>
      copy(checkId)?.subFactors.find((s) => s.id === subId)?.title ?? humanizeColumn(subId),
  };
}

const DEFAULT_LOOKUP = checkLookup(null);

/** Copy from DEFAULT_CHECKS only. Prefer `checkLookup(result.check_descriptors)`. */
export function checkCopy(id: string): CheckCopy | undefined {
  return DEFAULT_LOOKUP.copy(id);
}

/** Title from DEFAULT_CHECKS only. Prefer `checkLookup(result.check_descriptors)`. */
export function checkTitle(id: string): string {
  return DEFAULT_LOOKUP.title(id);
}

/** Sub-factor title from DEFAULT_CHECKS only. Prefer `checkLookup(result.check_descriptors)`. */
export function subFactorTitle(checkId: string, subId: string): string {
  return DEFAULT_LOOKUP.subFactorTitle(checkId, subId);
}
