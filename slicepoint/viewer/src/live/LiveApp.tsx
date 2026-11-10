// The live viewer shell: sign in, list jobs, start one, follow its steps, open its result.
// A result is rendered by the same ResultScreen and validated by the same
// viewmodel/load.ts path as a file opened in the static viewer.
import { useCallback, useEffect, useMemo, useState } from "react";
import { ErrorPanel } from "../components/Loader";
import { ResultScreen } from "../components/ResultScreen";
import { ThemeButton } from "../components/ThemeButton";
import { Button, Notice } from "../components/ui";
import { DISCLAIMER, MAX_FILE_BYTES, loadResultText, type LoadOutcome } from "../viewmodel";
import { createClient, type ApiClient } from "./client";
import { JobProgressPanel, JobsPanel, ReportLink } from "./Jobs";
import { SignIn } from "./SignIn";
import { StartAssessment } from "./StartAssessment";

type Session = "checking" | "signed_out" | "signed_in" | "unreachable";
type View = { kind: "home" } | { kind: "job"; id: string } | { kind: "result"; id: string };

function ResultLoader({ client, jobId, onBack }: { client: ApiClient; jobId: string; onBack: () => void }) {
  const [outcome, setOutcome] = useState<LoadOutcome | null>(null);

  useEffect(() => {
    let live = true;
    client
      .getResultText(jobId)
      .then((text): LoadOutcome => {
        if (text.length > MAX_FILE_BYTES) {
          return { ok: false, error: { title: "This result is too large to show", detail: "The service returned more than 50 MB.", problems: [] } };
        }
        return loadResultText(text);
      })
      .catch(
        (e: unknown): LoadOutcome => ({
          ok: false,
          error: { title: "The result could not be fetched", detail: e instanceof Error ? e.message : String(e), problems: [] },
        }),
      )
      .then((out) => live && setOutcome(out));
    return () => {
      live = false;
    };
  }, [client, jobId]);

  const back = (
    <Button variant="outline" size="sm" onClick={onBack}>
      ← All assessments
    </Button>
  );
  if (!outcome) return <p className="text-sm text-muted-foreground">Loading the result…</p>;
  if (!outcome.ok) return <ErrorPanel fileName={`job ${jobId.slice(0, 8)}`} error={outcome.error} onReset={onBack} actions={back} />;
  return (
    <>
      <div className="no-print mb-4 flex flex-wrap items-center gap-3">
        {back}
        <ReportLink client={client} jobId={jobId} />
      </div>
      <ResultScreen result={outcome.result} readNotes={outcome.compatNotes} source={`the result of job ${jobId.slice(0, 8)}`} />
    </>
  );
}

export function LiveApp({ fetchImpl, pollMs = 2000 }: { fetchImpl?: typeof fetch; pollMs?: number }) {
  const [session, setSession] = useState<Session>("checking");
  const [notice, setNotice] = useState<string | null>(null);
  const [view, setView] = useState<View>({ kind: "home" });

  const client = useMemo(
    () =>
      createClient({
        ...(fetchImpl ? { fetchImpl } : {}),
        onUnauthorized: () => {
          setSession("signed_out");
          setNotice("Your session ended. Sign in again.");
        },
      }),
    [fetchImpl],
  );

  useEffect(() => {
    let live = true;
    client
      .getSession()
      .then((s) => live && setSession(s.signed_in ? "signed_in" : "signed_out"))
      .catch(() => live && setSession("unreachable"));
    return () => {
      live = false;
    };
  }, [client]);

  useEffect(() => {
    if (session !== "signed_in" || view.kind !== "result") document.title = "SlicePoint";
  }, [session, view]);

  const home = useCallback(() => setView({ kind: "home" }), []);
  const showJob = useCallback((id: string) => setView({ kind: "job", id }), []);
  const openResult = useCallback((id: string) => setView({ kind: "result", id }), []);

  const signOut = async () => {
    try {
      await client.signOut();
    } catch {
      // the cookie is cleared or already invalid either way
    }
    setView({ kind: "home" });
    setNotice(null);
    setSession("signed_out");
  };

  return (
    <div className="min-h-screen bg-background text-foreground">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-10 focus:rounded focus:bg-background focus:p-2">
        Skip to content
      </a>
      <header className="no-print border-b">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-3">
          <button type="button" onClick={home} className="cursor-pointer text-left">
            <span className="block text-lg font-bold tracking-tight">SlicePoint</span>
            <span className="block text-xs text-muted-foreground">Is this AI a fit for our patients?</span>
          </button>
          <div className="flex flex-wrap items-center gap-2">
            {session === "signed_in" ? (
              <Button variant="outline" size="sm" onClick={() => void signOut()}>
                Sign out
              </Button>
            ) : null}
            <ThemeButton />
          </div>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-4 py-6">
        {session === "checking" ? <p className="text-sm text-muted-foreground">Connecting to the SlicePoint service…</p> : null}
        {session === "unreachable" ? (
          <Notice tone="problem">The SlicePoint service could not be reached. Check that it is running and reload the page.</Notice>
        ) : null}
        {session === "signed_out" ? (
          <SignIn
            client={client}
            notice={notice}
            onSignedIn={() => {
              setNotice(null);
              setView({ kind: "home" });
              setSession("signed_in");
            }}
          />
        ) : null}
        {session === "signed_in" && view.kind === "home" ? (
          <div className="space-y-6">
            <JobsPanel client={client} pollMs={pollMs} onShowJob={showJob} onOpenResult={openResult} />
            <StartAssessment client={client} onStarted={showJob} />
          </div>
        ) : null}
        {session === "signed_in" && view.kind === "job" ? (
          <JobProgressPanel client={client} jobId={view.id} pollMs={pollMs} onBack={home} onOpenResult={openResult} />
        ) : null}
        {session === "signed_in" && view.kind === "result" ? <ResultLoader key={view.id} client={client} jobId={view.id} onBack={home} /> : null}
      </main>
      <footer className="mx-auto max-w-6xl border-t px-4 py-6 text-sm">
        <p className="font-semibold">{DISCLAIMER}</p>
        <div className="mt-1">
          <Notice tone="skip">
            This page talks only to the SlicePoint service it was loaded from. Data and results stay on that server; nothing is
            sent anywhere else.
          </Notice>
        </div>
      </footer>
    </div>
  );
}
