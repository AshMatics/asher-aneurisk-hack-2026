import { useCallback, useEffect, useState } from "react";
import { DropZone, ErrorPanel, FileButton } from "./components/Loader";
import { ResultScreen } from "./components/ResultScreen";
import { ThemeButton } from "./components/ThemeButton";
import { Notice } from "./components/ui";
import { findSample } from "./fixtures";
import {
  DISCLAIMER,
  MAX_FILE_BYTES,
  loadResultData,
  loadResultText,
  type AssessmentResult,
  type LoadError,
} from "./viewmodel";

type State =
  | { kind: "empty" }
  | { kind: "error"; source: string; error: LoadError }
  | { kind: "loaded"; source: string; result: AssessmentResult; readNotes: readonly string[]; sample: boolean; seq: number };

// Each opened result gets a fresh ResultScreen (tab and score toggle reset).
let loads = 0;

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
    ? { kind: "loaded", source: `Sample: ${sample.title}`, result: out.result, readNotes: out.compatNotes, sample: true, seq: ++loads }
    : { kind: "error", source: `Sample: ${sample.title}`, error: out.error };
}

export function App() {
  const [state, setState] = useState<State>(initialState);

  const reset = useCallback(() => setState({ kind: "empty" }), []);

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
    setState(
      out.ok
        ? { kind: "loaded", source, result: out.result, readNotes: out.compatNotes, sample: false, seq: ++loads }
        : { kind: "error", source, error: out.error },
    );
  }, []);

  const openSample = useCallback((id: string) => {
    const s = findSample(id);
    if (!s) return;
    const out = loadResultData(s.data);
    setState(
      out.ok
        ? { kind: "loaded", source: `Sample: ${s.title}`, result: out.result, readNotes: out.compatNotes, sample: true, seq: ++loads }
        : { kind: "error", source: `Sample: ${s.title}`, error: out.error },
    );
  }, []);

  useEffect(() => {
    if (state.kind !== "loaded") document.title = "SlicePoint viewer";
  }, [state]);

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
            <ThemeButton />
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-4 py-6">
        {state.kind === "empty" ? <DropZone onFile={openFile} onSample={openSample} /> : null}
        {state.kind === "error" ? <ErrorPanel fileName={state.source} error={state.error} onFile={openFile} onReset={reset} /> : null}
        {state.kind === "loaded" ? (
          <ResultScreen key={state.seq} result={state.result} readNotes={state.readNotes} source={state.source} sample={state.sample} />
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
