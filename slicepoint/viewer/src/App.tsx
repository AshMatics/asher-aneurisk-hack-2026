import { useCallback, useEffect, useMemo, useState } from "react";
import { AboutPanel, CasesPanel, PerformancePanel, StrataPanel } from "./components/Panels";
import { ChecksSection, VerdictPanel } from "./components/Overview";
import { DropZone, ErrorPanel, FileButton } from "./components/Loader";
import { Tabs } from "./components/Tabs";
import { Button, Notice } from "./components/ui";
import { findSample } from "./fixtures";
import { applyTheme, readThemeChoice, saveThemeChoice, type ThemeChoice } from "./theme";
import {
  DISCLAIMER,
  MAX_FILE_BYTES,
  PROVISIONAL_BANNER,
  buildViewModel,
  loadResultData,
  loadResultText,
  type AssessmentResult,
  type LoadError,
} from "./viewmodel";

type State =
  | { kind: "empty" }
  | { kind: "error"; source: string; error: LoadError }
  | { kind: "loaded"; source: string; result: AssessmentResult; readNotes: readonly string[]; sample: boolean };

type TabId = "overview" | "performance" | "groups" | "cases" | "about";

function sampleFromQuery(): string | null {
  try {
    return new URLSearchParams(window.location.search).get("sample");
  } catch {
    return null;
  }
}

function initialState(): State {
  // `?sample=<id>` opens a sample that is built into the page (for demos and automated
  // screenshots). It can only select bundled samples; it never loads anything.
  const sample = findSample(sampleFromQuery());
  if (!sample) return { kind: "empty" };
  const out = loadResultData(sample.data);
  return out.ok
    ? { kind: "loaded", source: `Sample: ${sample.title}`, result: out.result, readNotes: out.compatNotes, sample: true }
    : { kind: "error", source: `Sample: ${sample.title}`, error: out.error };
}

const THEME_NEXT: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const THEME_LABEL: Record<ThemeChoice, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };

export function App() {
  const [state, setState] = useState<State>(initialState);
  const [tab, setTab] = useState<TabId>("overview");
  const [showScores, setShowScores] = useState(false);
  const [theme, setTheme] = useState<ThemeChoice>(readThemeChoice);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => applyTheme("system");
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, [theme]);

  const reset = useCallback(() => {
    setState({ kind: "empty" });
    setTab("overview");
    setShowScores(false);
  }, []);

  const openFile = useCallback(async (file: File) => {
    const source = file.name || "the file";
    if (file.size > MAX_FILE_BYTES) {
      setState({
        kind: "error",
        source,
        error: {
          title: "This file is too large to be a SlicePoint result",
          detail: `It is ${(file.size / 1024 / 1024).toFixed(0)} MB; a result is usually about 100 kB.`,
          problems: [],
        },
      });
      return;
    }
    let text: string;
    try {
      text = await file.text();
    } catch (e) {
      setState({
        kind: "error",
        source,
        error: { title: "The file could not be read", detail: "The browser refused to read it.", problems: [String(e)] },
      });
      return;
    }
    const out = loadResultText(text);
    setTab("overview");
    setShowScores(false);
    setState(
      out.ok
        ? { kind: "loaded", source, result: out.result, readNotes: out.compatNotes, sample: false }
        : { kind: "error", source, error: out.error },
    );
  }, []);

  const openSample = useCallback((id: string) => {
    const s = findSample(id);
    if (!s) return;
    const out = loadResultData(s.data);
    setTab("overview");
    setShowScores(false);
    setState(
      out.ok
        ? { kind: "loaded", source: `Sample: ${s.title}`, result: out.result, readNotes: out.compatNotes, sample: true }
        : { kind: "error", source: `Sample: ${s.title}`, error: out.error },
    );
  }, []);

  const view = useMemo(
    () => (state.kind === "loaded" ? buildViewModel(state.result, { showScores, readNotes: state.readNotes }) : null),
    [state, showScores],
  );

  useEffect(() => {
    if (state.kind === "loaded") document.title = `SlicePoint: ${view?.header.site ?? ""}`;
    else document.title = "SlicePoint viewer";
  }, [state, view]);

  // Jump from the verdict to a check card (both are on the overview tab).
  const jumpToCheck = useCallback((id: string) => {
    const el = document.getElementById(`check-${id}`);
    if (!el) return;
    el.scrollIntoView?.({ behavior: "smooth", block: "start" });
    el.focus({ preventScroll: true });
  }, []);

  // Drop a file anywhere on the page, also after a result is open.
  useEffect(() => {
    const over = (e: DragEvent) => e.preventDefault();
    const drop = (e: DragEvent) => {
      e.preventDefault();
      const f = e.dataTransfer?.files?.[0];
      if (f) void openFile(f);
    };
    window.addEventListener("dragover", over);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragover", over);
      window.removeEventListener("drop", drop);
    };
  }, [openFile]);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:rounded focus:bg-background focus:p-2">
        Skip to content
      </a>
      <header className="no-print border-b">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <button type="button" onClick={reset} className="cursor-pointer text-left">
            <span className="block text-lg font-bold tracking-tight">SlicePoint</span>
            <span className="block text-xs text-muted-foreground">Is this AI a fit for our patients?</span>
          </button>
          <div className="flex flex-wrap items-center gap-2">
            {state.kind !== "empty" ? <FileButton onFile={openFile} variant="outline" size="sm" label="Open another file" /> : null}
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                const next = THEME_NEXT[theme];
                setTheme(next);
                saveThemeChoice(next);
              }}
              aria-label={`${THEME_LABEL[theme]}. Switch to ${THEME_NEXT[theme]}.`}
            >
              {THEME_LABEL[theme]}
            </Button>
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-4 py-6">
        {state.kind === "empty" ? <DropZone onFile={openFile} onSample={openSample} /> : null}
        {state.kind === "error" ? <ErrorPanel fileName={state.source} error={state.error} onFile={openFile} onReset={reset} /> : null}
        {state.kind === "loaded" && view ? (
          <>
            <div className="mb-4">
              <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">SlicePoint fit check: {view.header.site}</h1>
              <p className="mt-1 text-sm text-muted-foreground">
                {view.header.subtitle} Generated {view.header.generated}.
              </p>
              <p className="mt-1 text-xs text-muted-foreground">
                Showing {state.source}
                {state.sample ? " (synthetic practice data)" : ""}.
              </p>
            </div>
            {view.scores.available ? (
              <div className="mb-4 rounded-md border-2 border-dashed border-watch bg-watch-bg p-3 text-sm text-foreground">
                <label className="flex cursor-pointer items-start gap-2 font-medium">
                  <input
                    type="checkbox"
                    className="mt-1 size-4"
                    checked={showScores}
                    onChange={(e) => setShowScores(e.target.checked)}
                  />
                  <span>
                    Show provisional scores (unratified, method {view.scores.methods.join(", ")})
                  </span>
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
        ) : null}
      </main>
      <footer className="mx-auto max-w-6xl border-t px-4 py-6 text-sm">
        <p className="font-semibold">{DISCLAIMER}</p>
        <div className="mt-1">
          <Notice tone="skip">
            This page reads files on this computer only and makes no network requests. Nothing you open here is sent anywhere.
          </Notice>
        </div>
      </footer>
    </div>
  );
}
