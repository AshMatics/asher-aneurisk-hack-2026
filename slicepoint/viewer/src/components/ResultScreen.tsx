// One validated AssessmentResult on screen: header, provisional-score gate and the tabs.
// Shared by the static viewer (a file the reader opened) and the live viewer (a job's
// result fetched from slicepoint-api). Both pass a result that went through
// viewmodel/load.ts, so both validate against the contract the same way.
import { useCallback, useEffect, useMemo, useState } from "react";
import { AboutPanel, CasesPanel, PerformancePanel, StrataPanel } from "./Panels";
import { ChecksSection, VerdictPanel } from "./Overview";
import { Tabs } from "./Tabs";
import { PROVISIONAL_BANNER, buildViewModel, type AssessmentResult } from "../viewmodel";

type TabId = "overview" | "performance" | "groups" | "cases" | "about";

export function ResultScreen({
  result,
  readNotes,
  source,
  sample = false,
}: {
  result: AssessmentResult;
  readNotes: readonly string[];
  /** Where the result came from, e.g. the file name. */
  source: string;
  sample?: boolean;
}) {
  const [tab, setTab] = useState<TabId>("overview");
  const [showScores, setShowScores] = useState(false);
  const view = useMemo(() => buildViewModel(result, { showScores, readNotes }), [result, showScores, readNotes]);

  useEffect(() => {
    document.title = `SlicePoint: ${view.header.site}`;
  }, [view.header.site]);

  // Jump from the verdict to a check card (both are on the overview tab).
  const jumpToCheck = useCallback((id: string) => {
    const el = document.getElementById(`check-${id}`);
    if (!el) return;
    el.scrollIntoView?.({ behavior: "smooth", block: "start" });
    el.focus({ preventScroll: true });
  }, []);

  return (
    <>
      <div className="mb-4">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">SlicePoint fit check: {view.header.site}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {view.header.subtitle} Generated {view.header.generated}.
        </p>
        <p className="mt-1 text-xs text-muted-foreground">
          Showing {source}
          {sample ? " (synthetic practice data)" : ""}.
        </p>
      </div>
      {view.scores.available ? (
        <div className="mb-4 rounded-md border-2 border-dashed border-watch bg-watch-bg p-3 text-sm text-foreground">
          <label className="flex cursor-pointer items-start gap-2 font-medium">
            <input type="checkbox" className="mt-1 size-4" checked={showScores} onChange={(e) => setShowScores(e.target.checked)} />
            <span>Show provisional scores (unratified, method {view.scores.methods.join(", ")})</span>
          </label>
          <p className="mt-1 pl-6 text-xs">{PROVISIONAL_BANNER}</p>
        </div>
      ) : null}
      <Tabs
        label="Result sections"
        active={tab}
        onChange={(id) => setTab(id as TabId)}
        tabs={[
          { id: "overview", label: "Overview" },
          { id: "performance", label: "Performance" },
          { id: "groups", label: "By group" },
          {
            id: "cases",
            label: "Cases to review",
            ...(view.cases.kind === "ok" ? { badge: String(view.cases.rows.length) } : {}),
          },
          { id: "about", label: "Methods & provenance" },
        ]}
      >
        {tab === "overview" ? (
          <>
            <VerdictPanel verdict={view.verdict} onJump={jumpToCheck} />
            <ChecksSection checks={view.checks} scores={view.scores} />
          </>
        ) : null}
        {tab === "performance" ? <PerformancePanel perf={view.performance} /> : null}
        {tab === "groups" ? <StrataPanel strata={view.strata} /> : null}
        {tab === "cases" ? <CasesPanel cases={view.cases} /> : null}
        {tab === "about" ? <AboutPanel about={view.about} /> : null}
      </Tabs>
    </>
  );
}
