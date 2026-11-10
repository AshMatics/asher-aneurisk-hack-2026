// Minimal shadcn-style primitives, written out instead of pulling in Radix: the viewer
// needs only buttons, cards, pills and a disclosure.
import { useId, useState, type ButtonHTMLAttributes, type ReactNode } from "react";
import type { KeyValue, StatusLabel, Tone } from "../viewmodel";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export const TONE_TEXT: Record<Tone, string> = {
  ok: "text-ok",
  watch: "text-watch",
  problem: "text-problem",
  skip: "text-skip",
};

export const TONE_SURFACE: Record<Tone, string> = {
  ok: "text-ok bg-ok-bg border-ok",
  watch: "text-watch bg-watch-bg border-watch",
  problem: "text-problem bg-problem-bg border-problem",
  skip: "text-skip bg-skip-bg border-skip",
};

type Variant = "default" | "outline" | "ghost" | "secondary";

const VARIANT: Record<Variant, string> = {
  default: "bg-primary text-primary-foreground hover:bg-primary/90",
  outline: "border border-input bg-background hover:bg-accent hover:text-accent-foreground",
  ghost: "hover:bg-accent hover:text-accent-foreground",
  secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
};

export function Button({
  variant = "default",
  size = "md",
  className,
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; size?: "sm" | "md" }) {
  return (
    <button
      type={type}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-md font-medium transition-colors",
        "disabled:pointer-events-none disabled:opacity-50 cursor-pointer",
        size === "sm" ? "h-8 px-3 text-sm" : "h-10 px-4 text-sm",
        VARIANT[variant],
        className,
      )}
      {...props}
    />
  );
}

export function Card({ className, children, ...rest }: { className?: string; children: ReactNode } & React.HTMLAttributes<HTMLElement>) {
  return (
    <section className={cx("rounded-lg border bg-card text-card-foreground shadow-sm", className)} {...rest}>
      {children}
    </section>
  );
}

/** Status as text plus colour; the glyph is decorative. */
export function StatusPill({ status, className }: { status: StatusLabel; className?: string }) {
  return (
    <span
      className={cx(
        "inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-xs font-semibold",
        TONE_SURFACE[status.tone],
        className,
      )}
    >
      <span aria-hidden="true">{status.glyph}</span>
      {status.label}
    </span>
  );
}

export function SectionTitle({ id, children, lead }: { id?: string; children: ReactNode; lead?: ReactNode }) {
  return (
    <div className="mb-3">
      <h2 id={id} className="text-xl font-semibold tracking-tight">
        {children}
      </h2>
      {lead ? <p className="mt-1 max-w-3xl text-sm text-muted-foreground">{lead}</p> : null}
    </div>
  );
}

export function Notice({ tone = "watch", children }: { tone?: Tone; children: ReactNode }) {
  return <div className={cx("rounded-md border-l-4 px-3 py-2 text-sm", TONE_SURFACE[tone])}>{children}</div>;
}

export function KeyValueList({ items }: { items: readonly KeyValue[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-1 text-sm sm:grid-cols-[minmax(10rem,max-content)_1fr]">
      {items.map((kv) => (
        <div key={kv.label} className="contents">
          <dt className="pt-1 font-medium sm:pt-0">{kv.label}</dt>
          <dd className={cx("min-w-0 break-words text-muted-foreground", kv.code && "font-mono text-xs leading-5")}>{kv.value}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A button that shows and hides a region (aria-expanded / aria-controls). */
export function Disclosure({
  label,
  children,
  defaultOpen = false,
  className,
}: {
  label: (open: boolean) => ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className={className}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        className="inline-flex cursor-pointer items-center gap-1 rounded-sm text-sm font-medium underline-offset-4 hover:underline"
      >
        <span aria-hidden="true" className={cx("inline-block transition-transform", open && "rotate-90")}>
          ▸
        </span>
        {label(open)}
      </button>
      <div id={id} hidden={!open} className="mt-2">
        {open ? children : null}
      </div>
    </div>
  );
}

/** A table that scrolls inside itself, never the page. */
export function TableScroll({ children, label }: { children: ReactNode; label?: string }) {
  return (
    <div className="max-w-full overflow-x-auto" role={label ? "region" : undefined} aria-label={label} tabIndex={label ? 0 : undefined}>
      {children}
    </div>
  );
}

export const TH = "border-b-2 px-2 py-2 text-left align-bottom text-xs font-semibold uppercase tracking-wide text-muted-foreground";
export const TD = "border-b px-2 py-1.5 align-top";
