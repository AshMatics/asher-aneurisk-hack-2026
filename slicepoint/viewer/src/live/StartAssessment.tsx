// Start one assessment: a site dataset against a stored reference or a reference dataset.
// Site ids are typed by the user and never derived from folder names.
import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { Button, Card, Notice } from "../components/ui";
import { PROVISIONAL_BANNER } from "../viewmodel";
import type { ApiClient, ReferenceInfo } from "./client";
import { EMPTY_FORM, validateStartForm, type FormErrors, type StartForm } from "./viewmodel";

const FIELD = "h-10 w-full rounded-md border border-input bg-background px-3 text-sm";

function Field({ label, error, hint, children, id }: { label: string; error?: string; hint?: string; children: ReactNode; id: string }) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-sm font-medium">
        {label}
      </label>
      {children}
      {hint ? <p className="text-xs text-muted-foreground">{hint}</p> : null}
      {error ? (
        <p id={`${id}-err`} className="text-xs font-medium text-problem">
          {error}
        </p>
      ) : null}
    </div>
  );
}

export function StartAssessment({ client, onStarted }: { client: ApiClient; onStarted: (jobId: string) => void }) {
  const uid = useId();
  const id = (name: string) => `${uid}-${name}`;
  const [form, setForm] = useState<StartForm>(EMPTY_FORM);
  const [errors, setErrors] = useState<FormErrors>({});
  const [datasets, setDatasets] = useState<readonly string[]>([]);
  const [references, setReferences] = useState<readonly ReferenceInfo[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    Promise.all([client.listDatasets(), client.listReferences()])
      .then(([d, r]) => {
        if (!live) return;
        setDatasets(d);
        setReferences(r);
      })
      .catch((e: unknown) => live && setLoadError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [client]);

  const set = <K extends keyof StartForm>(key: K, value: StartForm[K]) => setForm((f) => ({ ...f, [key]: value }));
  const described = (name: keyof StartForm) => (errors[name] ? { "aria-invalid": true, "aria-describedby": `${id(name)}-err` } : {});

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    const out = validateStartForm(form);
    if (!out.ok) {
      setErrors(out.errors);
      return;
    }
    setErrors({});
    setBusy(true);
    try {
      const accepted = await client.submitAssessment(out.request);
      onStarted(accepted.job_id);
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-4" aria-labelledby={id("h")}>
      <h2 id={id("h")} className="mb-3 text-lg font-semibold">
        Start an assessment
      </h2>
      {loadError ? <Notice tone="problem">Could not load datasets or references: {loadError}</Notice> : null}
      <form onSubmit={submit} noValidate className="grid gap-4 sm:grid-cols-2">
        <Field id={id("dataset")} label="Site dataset" error={errors.dataset}>
          <select id={id("dataset")} className={FIELD} value={form.dataset} onChange={(e) => set("dataset", e.target.value)} {...described("dataset")}>
            <option value="">Choose…</option>
            {datasets.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </Field>
        <Field id={id("siteId")} label="Site id" error={errors.siteId} hint="The site's stable id, e.g. hospital_b. Not taken from the dataset name.">
          <input id={id("siteId")} className={FIELD} value={form.siteId} onChange={(e) => set("siteId", e.target.value)} autoComplete="off" {...described("siteId")} />
        </Field>
        <Field id={id("siteName")} label="Site name (optional)" error={errors.siteName} hint="Shown in the report only.">
          <input id={id("siteName")} className={FIELD} value={form.siteName} onChange={(e) => set("siteName", e.target.value)} autoComplete="off" {...described("siteName")} />
        </Field>
        <Field id={id("onInconsistency")} label="If the data is inconsistent">
          <select
            id={id("onInconsistency")}
            className={FIELD}
            value={form.onInconsistency}
            onChange={(e) => set("onInconsistency", e.target.value === "drop_and_note" ? "drop_and_note" : "raise")}
          >
            <option value="raise">Stop with an error</option>
            <option value="drop_and_note">Drop the inconsistent rows and note it</option>
          </select>
        </Field>

        <fieldset className="space-y-3 sm:col-span-2">
          <legend className="text-sm font-medium">Reference</legend>
          <div className="flex flex-wrap gap-4 text-sm">
            <label className="flex items-center gap-2">
              <input type="radio" name={id("refmode")} checked={form.referenceMode === "stored"} onChange={() => set("referenceMode", "stored")} />
              Use a stored reference
            </label>
            <label className="flex items-center gap-2">
              <input type="radio" name={id("refmode")} checked={form.referenceMode === "dataset"} onChange={() => set("referenceMode", "dataset")} />
              Build from a reference dataset
            </label>
          </div>
          {form.referenceMode === "stored" ? (
            <Field
              id={id("referenceId")}
              label="Stored reference"
              error={errors.referenceId}
              hint={references.length ? undefined : "No stored references yet. Use a reference dataset instead."}
            >
              <select id={id("referenceId")} className={FIELD} value={form.referenceId} onChange={(e) => set("referenceId", e.target.value)} {...described("referenceId")}>
                <option value="">Choose…</option>
                {references.map((r) => (
                  <option key={r.reference_id} value={r.reference_id}>
                    {r.reference_id} (site {r.site_id}, {r.n_cases} cases)
                  </option>
                ))}
              </select>
            </Field>
          ) : (
            <div className="grid gap-4 sm:grid-cols-2">
              <Field id={id("referenceDataset")} label="Reference dataset" error={errors.referenceDataset}>
                <select
                  id={id("referenceDataset")}
                  className={FIELD}
                  value={form.referenceDataset}
                  onChange={(e) => set("referenceDataset", e.target.value)}
                  {...described("referenceDataset")}
                >
                  <option value="">Choose…</option>
                  {datasets.map((d) => (
                    <option key={d} value={d}>
                      {d}
                    </option>
                  ))}
                </select>
              </Field>
              <Field id={id("referenceSiteId")} label="Reference site id" error={errors.referenceSiteId} hint="Required. Never guessed from the dataset name.">
                <input
                  id={id("referenceSiteId")}
                  className={FIELD}
                  value={form.referenceSiteId}
                  onChange={(e) => set("referenceSiteId", e.target.value)}
                  autoComplete="off"
                  {...described("referenceSiteId")}
                />
              </Field>
            </div>
          )}
        </fieldset>

        <div className="rounded-md border-2 border-dashed border-watch bg-watch-bg p-3 text-sm sm:col-span-2">
          <label className="flex cursor-pointer items-start gap-2 font-medium">
            <input
              type="checkbox"
              className="mt-1 size-4"
              checked={form.showProvisionalScores}
              onChange={(e) => set("showProvisionalScores", e.target.checked)}
            />
            <span>Keep provisional 0-100 scores in the result (unratified)</span>
          </label>
          <p className="mt-1 pl-6 text-xs">{PROVISIONAL_BANNER}</p>
        </div>

        {submitError ? (
          <div role="alert" className="sm:col-span-2">
            <Notice tone="problem">The service did not accept the assessment: {submitError}</Notice>
          </div>
        ) : null}
        <div className="sm:col-span-2">
          <Button type="submit" disabled={busy}>
            {busy ? "Starting…" : "Start assessment"}
          </Button>
        </div>
      </form>
    </Card>
  );
}
