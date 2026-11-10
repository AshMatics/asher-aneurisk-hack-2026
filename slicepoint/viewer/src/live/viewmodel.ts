// Live-mode view-models: plain TypeScript, no React (ADR 0001 §7), no IO.
// Job and step labels, the job table, step progress and the start-form validation.
import { formatTimestamp, VERDICT, type StatusLabel } from "../viewmodel";
import { SITE_ID_PATTERN, SITE_NAME_MAX_LENGTH } from "./api.generated";
import type { AssessmentRequest, JobRecord, JobState, JobSummary, StepStatus } from "./client";

/** A job state says whether the pipeline ran, never whether the site passed. */
export const JOB_STATE: Readonly<Record<JobState, StatusLabel>> = {
  queued: { tone: "skip", label: "Queued", glyph: "…" },
  running: { tone: "watch", label: "Running", glyph: "↻" },
  succeeded: { tone: "ok", label: "Finished", glyph: "✓" },
  failed: { tone: "problem", label: "Failed", glyph: "✕" },
};

/** "Skipped" has its own tone, glyph and words: a step that did not run is never a pass. */
export const STEP_STATUS: Readonly<Record<StepStatus, StatusLabel>> = {
  pending: { tone: "skip", label: "Waiting", glyph: "○" },
  running: { tone: "watch", label: "Running", glyph: "↻" },
  succeeded: { tone: "ok", label: "Done", glyph: "✓" },
  failed: { tone: "problem", label: "Failed", glyph: "✕" },
  skipped: { tone: "skip", label: "Skipped, did not run", glyph: "⊘" },
};

export const SKIPPED_NOTE = "A skipped step did not run. It is not a pass, and the result says so.";

export function isActive(state: JobState): boolean {
  return state === "queued" || state === "running";
}

export function anyActive(jobs: readonly { readonly state: JobState }[]): boolean {
  return jobs.some((j) => isActive(j.state));
}

export interface JobRow {
  readonly id: string;
  readonly shortId: string;
  readonly site: string;
  readonly dataset: string;
  readonly state: StatusLabel;
  /** The verdict, only once the job has one. */
  readonly verdict: StatusLabel | null;
  readonly created: string;
  readonly canOpen: boolean;
}

export function jobRows(jobs: readonly JobSummary[]): JobRow[] {
  return jobs.map((j) => ({
    id: j.job_id,
    shortId: j.job_id.slice(0, 8),
    site: j.site_id,
    dataset: j.dataset,
    state: JOB_STATE[j.state],
    verdict: j.verdict ? VERDICT[j.verdict] : null,
    created: formatTimestamp(j.created_at),
    canOpen: j.state === "succeeded",
  }));
}

export interface StepRow {
  readonly id: string;
  readonly title: string;
  readonly status: StatusLabel;
  readonly skipped: boolean;
  readonly message: string | null;
  readonly duration: string | null;
}

export interface JobProgressView {
  readonly id: string;
  readonly title: string;
  readonly state: StatusLabel;
  readonly active: boolean;
  readonly canOpen: boolean;
  readonly verdict: StatusLabel | null;
  readonly summary: string;
  readonly steps: readonly StepRow[];
  readonly anySkipped: boolean;
  readonly error: string | null;
  readonly reference: string;
}

function duration(ms: number | null | undefined): string | null {
  if (ms === null || ms === undefined) return null;
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

export function jobProgress(job: JobRecord): JobProgressView {
  const steps = job.steps.map((s) => ({
    id: s.id,
    title: s.title,
    status: STEP_STATUS[s.status ?? "pending"],
    skipped: s.status === "skipped",
    message: s.message ?? null,
    duration: duration(s.duration_ms),
  }));
  const count = (st: StepStatus) => job.steps.filter((s) => (s.status ?? "pending") === st).length;
  const parts = [`${count("succeeded")} done`, `${count("skipped")} skipped`];
  if (count("failed")) parts.push(`${count("failed")} failed`);
  if (count("running")) parts.push(`${count("running")} running`);
  if (count("pending")) parts.push(`${count("pending")} waiting`);
  const r = job.request;
  return {
    id: job.job_id,
    title: r.site_name ? `${r.site_name} (${r.site_id})` : r.site_id,
    state: JOB_STATE[job.state],
    active: isActive(job.state),
    canOpen: job.state === "succeeded",
    verdict: job.audit.verdict ? VERDICT[job.audit.verdict] : null,
    summary: `${job.steps.length} steps: ${parts.join(", ")}.`,
    steps,
    anySkipped: steps.some((s) => s.skipped),
    error: job.error ?? null,
    reference: r.reference_id
      ? `stored reference ${r.reference_id}`
      : `dataset ${r.reference_dataset ?? "?"} (site ${r.reference_site_id ?? "?"})`,
  };
}

// --------------------------------------------------------------------------- start form

export interface StartForm {
  readonly dataset: string;
  readonly siteId: string;
  readonly siteName: string;
  readonly referenceMode: "stored" | "dataset";
  readonly referenceId: string;
  readonly referenceDataset: string;
  readonly referenceSiteId: string;
  readonly onInconsistency: "raise" | "drop_and_note";
  readonly showProvisionalScores: boolean;
}

export const EMPTY_FORM: StartForm = {
  dataset: "",
  siteId: "",
  siteName: "",
  referenceMode: "stored",
  referenceId: "",
  referenceDataset: "",
  referenceSiteId: "",
  onInconsistency: "raise",
  showProvisionalScores: false,
};

export type FormErrors = Partial<Record<keyof StartForm, string>>;

export type FormOutcome =
  | { readonly ok: true; readonly request: AssessmentRequest }
  | { readonly ok: false; readonly errors: FormErrors };

const SITE_ID = new RegExp(SITE_ID_PATTERN);
const SITE_ID_HELP = "Lower-case letters, digits, '-' and '_', starting with a letter or digit (at most 64).";

function siteIdError(value: string, what: string): string | undefined {
  if (!value) return `Enter the ${what}. It is never guessed from the dataset name.`;
  if (!SITE_ID.test(value)) return SITE_ID_HELP;
  return undefined;
}

/** Check the form and build the request. Nothing is filled in on the user's behalf. */
export function validateStartForm(f: StartForm): FormOutcome {
  const errors: FormErrors = {};
  const siteId = f.siteId.trim();
  const siteName = f.siteName.trim();
  if (!f.dataset) errors.dataset = "Choose the site's dataset.";
  const sid = siteIdError(siteId, "site id");
  if (sid) errors.siteId = sid;
  if (siteName.length > SITE_NAME_MAX_LENGTH) errors.siteName = `At most ${SITE_NAME_MAX_LENGTH} characters.`;
  const base = {
    dataset: f.dataset,
    site_id: siteId,
    site_name: siteName || null,
    on_inconsistency: f.onInconsistency,
    show_provisional_scores: f.showProvisionalScores,
  };
  let request: AssessmentRequest;
  if (f.referenceMode === "stored") {
    if (!f.referenceId) errors.referenceId = "Choose a stored reference.";
    request = { ...base, reference_id: f.referenceId };
  } else {
    const refSite = f.referenceSiteId.trim();
    if (!f.referenceDataset) errors.referenceDataset = "Choose the reference dataset.";
    const rid = siteIdError(refSite, "reference site id");
    if (rid) errors.referenceSiteId = rid;
    request = { ...base, reference_dataset: f.referenceDataset, reference_site_id: refSite };
  }
  return Object.keys(errors).length ? { ok: false, errors } : { ok: true, request };
}
