import { useMemo, useState } from "react";
import {
  filterCases,
  sortCases,
  type AboutView,
  type CaseSortKey,
  type CasesView,
  type PerformanceView,
  type ReviewReason,
  type SortDir,
  type StrataView,
} from "../viewmodel";
import { CiChart, DiceGauge, ShareBar } from "./charts";
import { Card, KeyValueList, Notice, SectionTitle, StatusPill, TD, TH, TableScroll, cx } from "./ui";

export function PerformancePanel({ perf }: { perf: PerformanceView }) {
  const b = perf.binary;
  return (
    <section aria-labelledby="perf-h" className="space-y-5">
      <SectionTitle id="perf-h" lead="As recorded in the result; nothing is recomputed in the browser.">
        AI performance on your sample
      </SectionTitle>
      <Card className="p-4">
        <h3 className="font-semibold">Finding aneurysms (AAA yes or no)</h3>
        {"kind" in b ? (
          <div className="mt-2">
            <Notice>{b.message}</Notice>
          </div>
        ) : (
          <>
            <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{b.lead}</p>
            <TableScroll>
              <table className="stack mt-2 w-full text-sm">
                <thead>
                  <tr>
                    <th scope="col" className={TH}>
                      Measure
                    </th>
                    <th scope="col" className={TH}>
                      Missing counts as wrong (primary)
                    </th>
                    <th scope="col" className={TH}>
                      When answered
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {b.rows.map((r) => (
                    <tr key={r.measure}>
                      <th scope="row" className={cx(TD, "text-left font-medium")}>
                        {r.measure}
                      </th>
                      <td className={TD} data-label="Primary">
                        {r.primary}
                      </td>
                      <td className={TD} data-label="When answered">
                        {r.answered}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
            <div className="mt-3">
              <CiChart rows={b.chart} label="Sensitivity and specificity with 95% Wilson intervals" />
            </div>
          </>
        )}
      </Card>
      <Card className="p-4">
        <h3 className="font-semibold">Measuring the aorta (AI minus label)</h3>
        <div className="mt-2">
          {perf.diameter.kind === "ok" ? (
            <>
              <KeyValueList items={perf.diameter.rows} />
              <div className="mt-3 space-y-2">
                {perf.diameter.bars.map((bar) => (
                  <div key={bar.label} className="grid grid-cols-1 items-center gap-1 text-sm sm:grid-cols-[minmax(0,22rem)_260px_4rem] sm:gap-3">
                    <span>{bar.label}</span>
                    <ShareBar share={bar.share} label={`${bar.label}: ${bar.display}`} />
                    <span className="font-semibold tabular-nums">{bar.display}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <Notice>{perf.diameter.message}</Notice>
          )}
        </div>
      </Card>
      <Card className="p-4">
        <h3 className="font-semibold">Outline quality (Dice)</h3>
        <div className="mt-2 space-y-2 text-sm">
          {perf.dice.kind === "ok" ? (
            <>
              <p>{perf.dice.text}</p>
              <DiceGauge median={perf.dice.median} mean={perf.dice.mean} markers={perf.dice.markers} />
              {perf.dice.markersNote ? <p className="text-muted-foreground">{perf.dice.markersNote}</p> : null}
            </>
          ) : (
            <Notice>{perf.dice.message}</Notice>
          )}
        </div>
      </Card>
    </section>
  );
}

export function StrataPanel({ strata }: { strata: StrataView }) {
  const [variable, setVariable] = useState("all");
  if (strata.kind === "not_recorded") {
    return (
      <section aria-labelledby="strata-h">
        <SectionTitle id="strata-h">Results by group</SectionTitle>
        <Notice>{strata.message}</Notice>
      </section>
    );
  }
  const groups = variable === "all" ? strata.groups : strata.groups.filter((g) => g.variable === variable);
  return (
    <section aria-labelledby="strata-h">
      <SectionTitle id="strata-h" lead={strata.lead}>
        Results by group
      </SectionTitle>
      {strata.groups.length === 0 ? (
        <Notice>No groups to show.</Notice>
      ) : (
        <>
          <label className="mb-3 flex flex-wrap items-center gap-2 text-sm">
            <span className="font-medium">Show</span>
            <select
              value={variable}
              onChange={(e) => setVariable(e.target.value)}
              className="h-9 rounded-md border border-input bg-background px-2"
            >
              <option value="all">All groupings</option>
              {strata.groups.map((g) => (
                <option key={g.variable} value={g.variable}>
                  {g.label}
                </option>
              ))}
            </select>
          </label>
          <TableScroll>
            <table className="stack w-full text-sm">
              <thead>
                <tr>
                  <th scope="col" className={TH}>Group</th>
                  <th scope="col" className={TH}>Scans</th>
                  <th scope="col" className={TH}>People</th>
                  <th scope="col" className={TH}>Bias</th>
                  <th scope="col" className={TH}>MAE</th>
                  <th scope="col" className={TH}>Within {strata.toleranceMm} mm</th>
                  <th scope="col" className={TH}>Sensitivity (95% CI)</th>
                </tr>
              </thead>
              {groups.map((g) => (
                <tbody key={g.variable}>
                  <tr>
                    <th scope="rowgroup" colSpan={7} className="bg-muted px-2 py-1.5 text-left font-semibold">
                      {g.label}
                    </th>
                  </tr>
                  {g.rows.map((r) => (
                    <tr key={r.level}>
                      <th scope="row" className={cx(TD, "text-left font-medium")}>
                        {r.level}
                      </th>
                      <td className={cx(TD, "tabular-nums")} data-label="Scans">{r.n}</td>
                      <td className={cx(TD, "tabular-nums")} data-label="People">{r.people}</td>
                      {r.tooFew ? (
                        <td colSpan={4} className={cx(TD, "italic text-muted-foreground")} data-label="Metrics">
                          {r.tooFewText}
                        </td>
                      ) : (
                        <>
                          <td className={cx(TD, "tabular-nums")} data-label="Bias">{r.bias}</td>
                          <td className={cx(TD, "tabular-nums")} data-label="MAE">{r.mae}</td>
                          <td className={cx(TD, "tabular-nums")} data-label={`Within ${strata.toleranceMm} mm`}>{r.within}</td>
                          <td className={cx(TD, "tabular-nums", r.sensSuppressed && "italic text-muted-foreground")} data-label="Sensitivity">
                            {r.sens}
                          </td>
                        </>
                      )}
                    </tr>
                  ))}
                </tbody>
              ))}
            </table>
          </TableScroll>
        </>
      )}
    </section>
  );
}

const SORT_LABEL: Record<CaseSortKey, string> = { priority: "Priority", error: "Size difference", case: "Case id" };

export function CasesPanel({ cases }: { cases: CasesView }) {
  const [reason, setReason] = useState<ReviewReason | "all">("all");
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<CaseSortKey>("priority");
  const [dir, setDir] = useState<SortDir>("asc");
  const rows = useMemo(
    () => (cases.kind === "ok" ? sortCases(filterCases(cases.rows, { reason, query }), sortKey, dir) : []),
    [cases, reason, query, sortKey, dir],
  );
  if (cases.kind === "not_recorded") {
    return (
      <section aria-labelledby="cases-h">
        <SectionTitle id="cases-h">Cases to review</SectionTitle>
        <Notice>{cases.message}</Notice>
      </section>
    );
  }
  const sortBy = (k: CaseSortKey) => {
    if (k === sortKey) setDir((d) => (d === "asc" ? "desc" : "asc"));
    else {
      setSortKey(k);
      setDir(k === "error" ? "desc" : "asc");
    }
  };
  const ariaSort = (k: CaseSortKey) => (k === sortKey ? (dir === "asc" ? "ascending" : "descending") : "none");
  const sortHeader = (k: CaseSortKey, text: string) => (
    <th scope="col" className={TH} aria-sort={ariaSort(k)}>
      <button type="button" onClick={() => sortBy(k)} className="inline-flex cursor-pointer items-center gap-1 uppercase hover:text-foreground">
        {text}
        <span aria-hidden="true">{k === sortKey ? (dir === "asc" ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );
  return (
    <section aria-labelledby="cases-h">
      <SectionTitle id="cases-h" lead={cases.lead}>
        Cases to review
      </SectionTitle>
      <p className="mb-3 text-sm font-medium">{cases.countLine}</p>
      {cases.rows.length === 0 ? (
        <p className="text-sm">No scans need review on these rules.</p>
      ) : (
        <>
          <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:flex-wrap sm:items-end">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Reason</span>
              <select
                value={reason}
                onChange={(e) => setReason(e.target.value as ReviewReason | "all")}
                className="h-9 rounded-md border border-input bg-background px-2"
              >
                <option value="all">All reasons ({cases.rows.length})</option>
                {cases.reasonsPresent.map((r) => (
                  <option key={r.code} value={r.code}>
                    {r.label} ({r.count})
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">Find case or person</span>
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="case id or p12"
                className="h-9 rounded-md border border-input bg-background px-2"
              />
            </label>
            <label className="flex flex-col gap-1 text-sm sm:hidden">
              <span className="font-medium">Sort by</span>
              <select
                value={`${sortKey}:${dir}`}
                onChange={(e) => {
                  const [k, d] = e.target.value.split(":") as [CaseSortKey, SortDir];
                  setSortKey(k);
                  setDir(d);
                }}
                className="h-9 rounded-md border border-input bg-background px-2"
              >
                <option value="priority:asc">Most urgent first</option>
                <option value="error:desc">Largest size difference first</option>
                <option value="case:asc">Case id</option>
              </select>
            </label>
          </div>
          <p className="sr-only" aria-live="polite">
            {rows.length} of {cases.rows.length} flagged cases shown, sorted by {SORT_LABEL[sortKey]}.
          </p>
          <TableScroll>
            <table className="stack w-full text-sm">
              <thead>
                <tr>
                  {sortHeader("case", "Case")}
                  <th scope="col" className={TH}>Person</th>
                  {sortHeader("priority", "Why")}
                  <th scope="col" className={TH}>Label</th>
                  <th scope="col" className={TH}>AI call</th>
                  <th scope="col" className={TH}>Label size</th>
                  <th scope="col" className={TH}>AI size</th>
                  {sortHeader("error", "Difference")}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.caseId} data-testid="case-row">
                    <th scope="row" className={cx(TD, "text-left font-mono text-xs font-normal")}>
                      {r.caseId}
                    </th>
                    <td className={TD} data-label="Person">{r.personGroup}</td>
                    <td className={cx(TD, "min-w-[12rem]")} data-label="Why">
                      <span className="mr-1 rounded bg-muted px-1 text-xs font-semibold">P{r.priority}</span>
                      {r.why.join("; ")}
                    </td>
                    <td className={TD} data-label="Label">{r.label}</td>
                    <td className={TD} data-label="AI call">{r.aiCall}</td>
                    <td className={cx(TD, "tabular-nums whitespace-nowrap")} data-label="Label size">{r.labelSize}</td>
                    <td className={cx(TD, "tabular-nums whitespace-nowrap")} data-label="AI size">{r.aiSize}</td>
                    <td className={cx(TD, "tabular-nums whitespace-nowrap")} data-label="Difference">{r.difference}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
          {rows.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">No flagged case matches the filter.</p> : null}
          <p className="mt-2 text-xs text-muted-foreground">
            P1 missed or unanswered aneurysm, P2 no answer, P3 size error beyond the tolerance, P4 false alarm.
          </p>
        </>
      )}
    </section>
  );
}

export function AboutPanel({ about }: { about: AboutView }) {
  const t = about.thresholds;
  return (
    <div className="space-y-6">
      <section aria-labelledby="notes-h">
        <SectionTitle id="notes-h">Notes from the run</SectionTitle>
        {about.notes.length ? (
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {about.notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No notes in this result.</p>
        )}
      </section>
      <section aria-labelledby="methods-h">
        <SectionTitle id="methods-h">Methods and limits</SectionTitle>
        <div className="grid gap-4 lg:grid-cols-2">
          <Card className="p-4">
            <h3 className="font-semibold">Methods</h3>
            <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm">
              {about.methods.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ol>
          </Card>
          <Card className="p-4">
            <h3 className="font-semibold">Limits</h3>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
              {about.limits.map((m) => (
                <li key={m}>{m}</li>
              ))}
            </ul>
          </Card>
        </div>
      </section>
      <section aria-labelledby="thr-h">
        <SectionTitle id="thr-h" lead="The resolved threshold profile this run used, as stored in the result.">
          Thresholds used
        </SectionTitle>
        {t.kind === "not_recorded" ? (
          <Notice>{t.message}</Notice>
        ) : (
          <div className="space-y-4">
            <div className="grid gap-4 lg:grid-cols-2">
              <Card className="p-4">
                <h3 className="mb-2 font-semibold">Decision rules</h3>
                <KeyValueList items={t.rules} />
              </Card>
              <Card className="p-4">
                <h3 className="mb-2 font-semibold">Check targets (used only by provisional scores)</h3>
                <KeyValueList items={t.targets} />
              </Card>
            </div>
            <Card className="p-4">
              <h3 className="mb-2 font-semibold">Profile</h3>
              <KeyValueList items={t.profile} />
            </Card>
            <Card className="p-4">
              <h3 className="font-semibold">Trigger lines ({t.triggers.length})</h3>
              <TableScroll label="Trigger lines">
                <table className="stack mt-2 w-full text-sm">
                  <thead>
                    <tr>
                      <th scope="col" className={TH}>Trigger</th>
                      <th scope="col" className={TH}>Watch at</th>
                      <th scope="col" className={TH}>Problem at</th>
                      <th scope="col" className={TH}>Direction</th>
                      <th scope="col" className={TH}>Unit</th>
                      <th scope="col" className={TH}>Inclusive</th>
                    </tr>
                  </thead>
                  <tbody>
                    {t.triggers.map((r) => (
                      <tr key={r.name}>
                        <th scope="row" className={cx(TD, "text-left font-medium")}>{r.name}</th>
                        <td className={cx(TD, "tabular-nums")} data-label="Watch at">{r.yellow}</td>
                        <td className={cx(TD, "tabular-nums")} data-label="Problem at">{r.red}</td>
                        <td className={TD} data-label="Direction">{r.worse}</td>
                        <td className={TD} data-label="Unit">{r.kind}</td>
                        <td className={TD} data-label="Inclusive">{r.inclusive}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableScroll>
            </Card>
            <div className="grid gap-4 lg:grid-cols-2">
              <Card className="p-4">
                <h3 className="mb-2 font-semibold">Parameters ({t.parameters.length})</h3>
                <KeyValueList items={t.parameters} />
              </Card>
              <Card className="p-4">
                <h3 className="mb-2 font-semibold">Where each value comes from ({t.sources.length})</h3>
                <KeyValueList items={t.sources} />
              </Card>
            </div>
          </div>
        )}
      </section>
      <section aria-labelledby="prov-h">
        <SectionTitle id="prov-h">Provenance</SectionTitle>
        <Card className="p-4">
          <KeyValueList items={about.provenance} />
          {about.readNotes.length ? (
            <div className="mt-3 text-sm">
              <p className="font-medium">How the viewer read this file</p>
              <ul className="list-disc pl-5 text-muted-foreground">
                {about.readNotes.map((n) => (
                  <li key={n}>{n}</li>
                ))}
              </ul>
            </div>
          ) : null}
        </Card>
        <h3 className="mb-1 mt-4 font-semibold">Pipeline steps</h3>
        <p className="mb-2 text-sm text-muted-foreground">{about.stepsLine}</p>
        <TableScroll>
          <table className="stack w-full text-sm">
            <thead>
              <tr>
                <th scope="col" className={TH}>Step</th>
                <th scope="col" className={TH}>State</th>
                <th scope="col" className={TH}>Detail</th>
              </tr>
            </thead>
            <tbody>
              {about.steps.map((s) => (
                <tr key={s.step} className={s.status.tone === "ok" ? undefined : "bg-muted/60"}>
                  <th scope="row" className={cx(TD, "text-left font-mono text-xs font-normal")}>{s.step}</th>
                  <td className={TD} data-label="State">
                    <StatusPill status={s.status} />
                  </td>
                  <td className={TD} data-label="Detail">{s.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </TableScroll>
      </section>
    </div>
  );
}
