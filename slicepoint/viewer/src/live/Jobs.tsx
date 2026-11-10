// The job list and one job's step-by-step progress.
import { useCallback, useEffect, useState } from "react";
import { Button, Card, Notice, StatusPill, TableScroll, TD, TH, cx } from "../components/ui";
import type { ApiClient, JobRecord, JobSummary } from "./client";
import { SKIPPED_NOTE, anyActive, jobProgress, jobRows } from "./viewmodel";
import { usePoll } from "./usePoll";

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function ReportLink({ client, jobId, className }: { client: ApiClient; jobId: string; className?: string }) {
  return (
    <a
      href={client.reportUrl(jobId)}
      target="_blank"
      rel="noopener noreferrer"
      className={cx("text-sm font-medium underline underline-offset-4", className)}
    >
      HTML report<span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

export function JobsPanel({
  client,
  pollMs,
  onShowJob,
  onOpenResult,
}: {
  client: ApiClient;
  pollMs: number;
  onShowJob: (id: string) => void;
  onOpenResult: (id: string) => void;
}) {
  const [jobs, setJobs] = useState<readonly JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      client.listJobs().then(
        (j) => {
          setJobs(j);
          setError(null);
        },
        (e: unknown) => setError(errorText(e)),
      ),
    [client],
  );

  useEffect(() => {
    void load();
  }, [load]);
  const active = jobs !== null && anyActive(jobs);
  usePoll(load, active, pollMs);

  const rows = jobRows(jobs ?? []);
  return (
    <Card className="p-4" aria-labelledby="jobs-h">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 id="jobs-h" className="text-lg font-semibold">
          Assessments
        </h2>
        <div className="flex items-center gap-2">
          {active ? <span className="text-xs text-muted-foreground">Updating while jobs run…</span> : null}
          <Button variant="outline" size="sm" onClick={() => void load()}>
            Refresh
          </Button>
        </div>
      </div>
      {error ? <Notice tone="problem">Could not load the job list: {error}</Notice> : null}
      {jobs === null && !error ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
      {jobs !== null && !rows.length ? <p className="text-sm text-muted-foreground">No assessments yet. Start one below.</p> : null}
      {rows.length ? (
        <TableScroll label="Assessments">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                <th className={TH}>Site</th>
                <th className={TH}>Dataset</th>
                <th className={TH}>Job</th>
                <th className={TH}>Verdict</th>
                <th className={TH}>Created</th>
                <th className={TH}>
                  <span className="sr-only">Actions</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} data-testid={`job-${r.id}`}>
                  <td className={cx(TD, "font-medium")}>{r.site}</td>
                  <td className={TD}>{r.dataset}</td>
                  <td className={TD}>
                    <StatusPill status={r.state} />
                  </td>
                  <td className={TD}>{r.verdict ? <StatusPill status={r.verdict} /> : <span className="text-muted-foreground">none yet</span>}</td>
                  <td className={cx(TD, "whitespace-nowrap")}>{r.created}</td>
                  <td className={cx(TD, "whitespace-nowrap")}>
                    <div className="flex flex-wrap items-center gap-2">
                      <Button variant="ghost" size="sm" onClick={() => onShowJob(r.id)} aria-label={`Steps for ${r.site} job ${r.shortId}`}>
                        Steps
                      </Button>
                      {r.canOpen ? (
                        <>
                          <Button size="sm" onClick={() => onOpenResult(r.id)} aria-label={`Open result for ${r.site} job ${r.shortId}`}>
                            Open result
                          </Button>
                          <ReportLink client={client} jobId={r.id} />
                        </>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      ) : null}
      <p className="mt-2 text-xs text-muted-foreground">
        &ldquo;Finished&rdquo; means the pipeline ran. It says nothing about fit: read the verdict.
      </p>
    </Card>
  );
}

export function JobProgressPanel({
  client,
  jobId,
  pollMs,
  onBack,
  onOpenResult,
}: {
  client: ApiClient;
  jobId: string;
  pollMs: number;
  onBack: () => void;
  onOpenResult: (id: string) => void;
}) {
  const [job, setJob] = useState<JobRecord | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    () =>
      client.getJob(jobId).then(
        (j) => {
          setJob(j);
          setError(null);
        },
        (e: unknown) => setError(errorText(e)),
      ),
    [client, jobId],
  );

  useEffect(() => {
    void load();
  }, [load]);
  const view = job ? jobProgress(job) : null;
  usePoll(load, view?.active ?? false, pollMs);

  return (
    <div className="space-y-4">
      <Button variant="outline" size="sm" onClick={onBack}>
        ← All assessments
      </Button>
      {error ? <Notice tone="problem">Could not load the job: {error}</Notice> : null}
      {!view && !error ? <p className="text-sm text-muted-foreground">Loading…</p> : null}
      {view ? (
        <Card className="p-4" aria-labelledby="job-h">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h1 id="job-h" className="text-xl font-semibold">
                Assessment of {view.title}
              </h1>
              <p className="text-sm text-muted-foreground">
                Against {view.reference}. Job {view.id}.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <StatusPill status={view.state} />
              {view.verdict ? <StatusPill status={view.verdict} /> : null}
            </div>
          </div>
          <p className="mt-3 text-sm" aria-live="polite" data-testid="job-summary">
            {view.summary}
          </p>
          {view.error ? (
            <div className="mt-2">
              <Notice tone="problem">{view.error}</Notice>
            </div>
          ) : null}
          <ol className="mt-3 space-y-2" aria-label="Pipeline steps">
            {view.steps.map((s) => (
              <li
                key={s.id}
                data-testid={`step-${s.id}`}
                data-status={s.status.label}
                className={cx(
                  "flex flex-wrap items-start justify-between gap-2 rounded-md border px-3 py-2",
                  s.skipped && "border-dashed bg-skip-bg italic",
                )}
              >
                <div className="min-w-0">
                  <p className="font-medium">{s.title}</p>
                  {s.message ? <p className="text-xs text-muted-foreground">{s.message}</p> : null}
                </div>
                <div className="flex items-center gap-2 not-italic">
                  {s.duration ? <span className="text-xs text-muted-foreground">{s.duration}</span> : null}
                  <StatusPill status={s.status} className={s.skipped ? "border-dashed" : undefined} />
                </div>
              </li>
            ))}
          </ol>
          {view.anySkipped ? <p className="mt-2 text-xs text-muted-foreground">{SKIPPED_NOTE}</p> : null}
          {view.canOpen ? (
            <div className="mt-4 flex flex-wrap items-center gap-3">
              <Button onClick={() => onOpenResult(view.id)}>Open result</Button>
              <ReportLink client={client} jobId={view.id} />
            </div>
          ) : null}
        </Card>
      ) : null}
    </div>
  );
}
