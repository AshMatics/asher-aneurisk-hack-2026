import type { CheckCard as CheckCardView, ScoresView, VerdictView } from "../viewmodel";
import { ShareBar } from "./charts";
import { Disclosure, Notice, SectionTitle, StatusPill, TD, TH, TONE_SURFACE, TONE_TEXT, TableScroll, cx } from "./ui";

export function VerdictPanel({ verdict, onJump }: { verdict: VerdictView; onJump: (checkId: string) => void }) {
  const v = verdict;
  const o = v.override;
  const named = [
    ...v.problems.map((p) => ({ ...p, kind: "Problem" })),
    ...v.watches.map((p) => ({ ...p, kind: "Watch" })),
    ...v.notEvaluated.map((p) => ({ ...p, kind: "Not evaluated" })),
  ];
  return (
    <section aria-labelledby="verdict-h" className={cx("rounded-lg border-2 p-4 sm:p-5", TONE_SURFACE[v.final.tone])}>
      <h2 id="verdict-h" className="text-xs font-semibold uppercase tracking-widest">
        {o ? "Final decision" : "Verdict"}
      </h2>
      <div className="mt-2 flex flex-col gap-3 sm:flex-row sm:items-start sm:gap-5">
        <p className="shrink-0 text-3xl font-extrabold tracking-tight sm:text-4xl" data-testid="final-verdict">
          <span aria-hidden="true">{v.final.glyph} </span>
          {v.final.label}
        </p>
        <div className="min-w-0 space-y-2 text-foreground">
          {o ? (
            <div className="rounded-md border border-current bg-background/70 p-3 text-sm" data-testid="override">
              <p className="font-semibold">
                Human decision: changed from {o.derived.label} to {o.final.label}
              </p>
              <p className="mt-1">
                By <strong>{o.by}</strong> on <time dateTime={o.atIso}>{o.at}</time>.
              </p>
              <p className="mt-1">
                <span className="font-medium">Reason:</span> {o.note}
              </p>
            </div>
          ) : null}
          <p className="text-base sm:text-lg">
            {o ? <span className="font-medium">The checks alone gave {v.derived.label}: </span> : null}
            {v.sentence}
          </p>
          {v.selfComparison ? (
            <p className="rounded-md border border-current bg-background/70 p-3 text-sm" role="note" data-testid="self-comparison">
              <strong>Self-comparison:</strong> {v.selfComparison}
            </p>
          ) : null}
          <p className="text-sm text-muted-foreground">
            {v.counts.problem} problem, {v.counts.watch} watch, {v.counts.ok} ok, {v.counts.notEvaluated} not evaluated.
          </p>
          {named.length ? (
            <ul className="flex flex-wrap gap-2" aria-label="Checks that need attention">
              {named.map((n) => (
                <li key={n.id}>
                  <button
                    type="button"
                    onClick={() => onJump(n.id)}
                    className="cursor-pointer rounded-md border border-current bg-background/60 px-2 py-0.5 text-sm hover:bg-background"
                  >
                    {n.kind}: {n.title}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          {v.notEvaluated.length ? (
            <p className="text-sm">
              <strong>Not evaluated:</strong> {v.notEvaluated.map((n) => n.title).join(", ")}. A check that did not run
              never counts as passed.
            </p>
          ) : null}
          <p className="text-xs text-muted-foreground">{v.disclaimer}</p>
        </div>
      </div>
    </section>
  );
}

function EvidenceDetail({ card }: { card: CheckCardView }) {
  return (
    <div className="space-y-3 text-sm">
      {card.subFactors.length ? (
        <div>
          <h4 className="font-semibold">Sub-factors</h4>
          <ul className="mt-1 space-y-0.5">
            {card.subFactors.map((s) => (
              <li key={s.id} className="flex items-start justify-between gap-3">
                <span>{s.title}</span>
                <span className={cx("shrink-0 text-xs font-semibold", s.failing ? TONE_TEXT[card.status.tone] : "text-muted-foreground")}>
                  {s.failing ? "Failing" : "Not flagged"}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {card.evidence.map((g) => (
        <div key={g.factor} className="rounded-md border p-2">
          <div className="flex items-start justify-between gap-2">
            <h4 className="font-semibold">{g.title}</h4>
            <StatusPill status={g.status} />
          </div>
          {g.text ? <p className="mt-1 text-muted-foreground">{g.text}</p> : null}
          {g.rows.length ? (
            <TableScroll>
              <table className="mt-1 w-full text-xs">
                <tbody>
                  {g.rows.map((r) => (
                    <tr key={r.key}>
                      <th scope="row" title={r.key} className={cx(TD, "text-left font-normal")}>
                        {r.label}
                      </th>
                      <td className={cx(TD, "text-right tabular-nums")}>{r.value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </TableScroll>
          ) : null}
        </div>
      ))}
      {card.otherEvidence.length ? (
        <div>
          <h4 className="font-semibold">Other numbers</h4>
          <TableScroll>
            <table className="mt-1 w-full text-xs">
              <thead>
                <tr>
                  <th scope="col" className={TH}>
                    Item
                  </th>
                  <th scope="col" className={cx(TH, "text-right")}>
                    Value
                  </th>
                </tr>
              </thead>
              <tbody>
                {card.otherEvidence.map((r) => (
                  <tr key={r.key}>
                    <th scope="row" title={r.key} className={cx(TD, "text-left font-normal")}>
                      {r.label}
                    </th>
                    <td className={cx(TD, "text-right tabular-nums")}>
                      {r.value}
                      {r.note ? <span className="block text-muted-foreground">{r.note}</span> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </TableScroll>
        </div>
      ) : null}
      {card.nEffectiveMethod ? (
        <p className="text-xs text-muted-foreground">
          Effective n method: <code className="font-mono">{card.nEffectiveMethod}</code>
        </p>
      ) : null}
    </div>
  );
}

export function CheckCard({ card }: { card: CheckCardView }) {
  const hasDetail = card.state === "evaluated" && (card.evidence.length > 0 || card.otherEvidence.length > 0 || card.subFactors.length > 0);
  return (
    <article
      id={`check-${card.id}`}
      data-check-id={card.id}
      aria-labelledby={`check-h-${card.id}`}
      tabIndex={-1}
      className="flex min-w-0 flex-col gap-2 rounded-lg border bg-card p-4 shadow-sm focus-visible:outline-2"
    >
      <header className="flex items-start justify-between gap-3">
        <h3 id={`check-h-${card.id}`} className="text-base font-semibold leading-snug">
          {card.title}
        </h3>
        <StatusPill status={card.status} />
      </header>
      {card.asks ? <p className="text-sm text-muted-foreground">{card.asks}</p> : null}
      {!card.known ? (
        <p className="text-xs text-muted-foreground">
          Check <code className="font-mono">{card.id}</code> is not one of the five built-in checks; its names are shown as recorded.
        </p>
      ) : null}
      {card.state !== "evaluated" ? (
        <p className="text-sm">
          <strong>Why:</strong> {card.reason}
        </p>
      ) : (
        <p className="text-sm text-muted-foreground">{card.nLine}</p>
      )}
      {card.failing.length ? (
        <div className="text-sm">
          <strong>Failing sub-factors:</strong>
          <ul className="mt-1 list-disc pl-5">
            {card.failing.map((s) => (
              <li key={s.id}>{s.title}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {card.findings.length ? (
        <ul className="space-y-1 text-sm">
          {card.findings.map((f, i) => (
            <li key={i}>
              <span className={cx("font-semibold", TONE_TEXT[f.status.tone])}>{f.status.label}:</span> {f.text}
            </li>
          ))}
        </ul>
      ) : card.summary ? (
        <p className="text-sm">{card.summary}</p>
      ) : null}
      {card.score ? (
        <div className="rounded-md border border-dashed border-watch p-2 text-sm" data-testid={`score-${card.id}`}>
          <p>
            Provisional score: <strong>{card.score.display}</strong> / 100
            {card.score.target !== null ? ` (target ${card.score.target})` : ""}{" "}
            <span className="text-muted-foreground">[{card.score.method}, not validated]</span>
          </p>
          <ShareBar
            share={card.score.value / 100}
            target={card.score.target === null ? null : card.score.target / 100}
            label={`Provisional score ${card.score.display} of 100${card.score.target !== null ? `, target ${card.score.target}` : ""}`}
          />
        </div>
      ) : null}
      <p className="border-t pt-2 text-sm">
        <strong>What this means:</strong> {card.means}
      </p>
      {hasDetail ? (
        <Disclosure label={(open) => (open ? "Hide the numbers" : "Show the numbers")}>
          <EvidenceDetail card={card} />
        </Disclosure>
      ) : null}
    </article>
  );
}

export function ChecksSection({ checks, scores }: { checks: readonly CheckCardView[]; scores: ScoresView }) {
  return (
    <section aria-labelledby="checks-h" className="mt-6">
      <SectionTitle
        id="checks-h"
        lead={
          <>
            Each check compares your data with the reference. Status is Problem, Watch or OK; a check that could not run is
            shown as Not evaluated and never counts as passed. <em>n</em> is the number of scans the check used;{" "}
            <em>effective n</em> discounts repeat scans of the same person.
          </>
        }
      >
        Health checks
      </SectionTitle>
      {scores.shown ? (
        <div className="mb-3">
          <Notice tone="watch">
            Showing provisional scores ({scores.methods.join(", ")}). They are not validated and must not drive a decision.
          </Notice>
        </div>
      ) : null}
      <div className="grid grid-cols-1 items-start gap-4 md:grid-cols-2 xl:grid-cols-3">
        {checks.map((c) => (
          <CheckCard key={c.id} card={c} />
        ))}
      </div>
    </section>
  );
}
