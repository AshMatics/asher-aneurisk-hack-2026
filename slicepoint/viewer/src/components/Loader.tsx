// Open a result.json: file picker, drag and drop, or a bundled sample. The file is read
// with the File API in this browser; nothing is uploaded or fetched.
import { useRef, useState, type DragEvent } from "react";
import { SAMPLES } from "../fixtures";
import { MAX_FILE_BYTES, SCHEMA_VERSION, type LoadError } from "../viewmodel";
import { Button, Card, cx } from "./ui";

export function FileButton({
  onFile,
  variant = "default",
  label = "Open result.json",
  size = "md",
}: {
  onFile: (file: File) => void;
  variant?: "default" | "outline";
  label?: string;
  size?: "sm" | "md";
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={input}
        type="file"
        accept=".json,application/json"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="file-input"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
      <Button variant={variant} size={size} onClick={() => input.current?.click()}>
        {label}
      </Button>
    </>
  );
}

export function DropZone({ onFile, onSample }: { onFile: (file: File) => void; onSample: (id: string) => void }) {
  const [over, setOver] = useState(false);
  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setOver(false);
    const f = e.dataTransfer.files?.[0];
    if (f) onFile(f);
  };
  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">Is this AI a fit for our patients and scanners?</h1>
        <p className="mt-2 text-muted-foreground">
          Open the <code className="font-mono text-sm">result.json</code> that <code className="font-mono text-sm">slicepoint assess</code>{" "}
          wrote to see the verdict, the five health checks and the evidence behind them.
        </p>
      </div>
      <div
        data-testid="drop-zone"
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cx(
          "flex flex-col items-center gap-3 rounded-lg border-2 border-dashed p-8 text-center transition-colors",
          over ? "border-foreground bg-muted" : "border-input",
        )}
      >
        <p className="font-medium">Drop result.json here</p>
        <p className="text-sm text-muted-foreground">or</p>
        <FileButton onFile={onFile} />
      </div>
      <Card className="p-4">
        <h2 className="font-semibold">Private by design</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          The file is read in this browser only. This page makes no network requests: nothing is uploaded, nothing is
          tracked, and it works offline, so it can be opened on a hospital computer next to patient data. It reads
          results written against SlicePoint contract version {SCHEMA_VERSION}.
        </p>
      </Card>
      <section aria-labelledby="samples-h">
        <h2 id="samples-h" className="font-semibold">
          Try a sample
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Results built into this page from the synthetic hackathon practice data (no real patients), compared with
          Hospital A as the reference.
        </p>
        <ul className="mt-3 grid gap-2 sm:grid-cols-2">
          {SAMPLES.map((s) => (
            <li key={s.id}>
              <button
                type="button"
                onClick={() => onSample(s.id)}
                className="h-full w-full cursor-pointer rounded-md border bg-card p-3 text-left hover:bg-accent"
              >
                <span className="block font-medium">{s.title}</span>{" "}
                <span className="block text-sm text-muted-foreground">{s.description}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

export function ErrorPanel({ fileName, error, onFile, onReset }: { fileName: string; error: LoadError; onFile: (f: File) => void; onReset: () => void }) {
  return (
    <div className="mx-auto max-w-3xl">
      <div role="alert" className="rounded-lg border-2 border-problem bg-problem-bg p-4 text-foreground sm:p-5">
        <p className="text-xs font-semibold uppercase tracking-widest text-problem">
          <span aria-hidden="true">✕ </span>Could not open {fileName}
        </p>
        <h1 className="mt-1 text-xl font-semibold">{error.title}</h1>
        <p className="mt-2 text-sm">{error.detail}</p>
        {error.problems.length ? (
          <ul className="mt-3 list-disc space-y-0.5 pl-5 font-mono text-xs" aria-label="Problems found">
            {error.problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        ) : null}
      </div>
      <div className="mt-4 flex flex-wrap gap-2">
        <FileButton onFile={onFile} label="Open another file" />
        <Button variant="outline" onClick={onReset}>
          Back to start
        </Button>
      </div>
      <p className="mt-3 text-xs text-muted-foreground">Maximum file size {Math.round(MAX_FILE_BYTES / 1024 / 1024)} MB.</p>
    </div>
  );
}
