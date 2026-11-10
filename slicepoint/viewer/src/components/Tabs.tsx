// WAI-ARIA tabs: arrow keys, Home and End move between tabs; only the active tab is in
// the tab order. The tab strip scrolls inside itself on a narrow screen, never the page.
import { useRef, type KeyboardEvent, type ReactNode } from "react";
import { cx } from "./ui";

export interface TabDef {
  readonly id: string;
  readonly label: string;
  /** Short extra text after the label, e.g. a count. */
  readonly badge?: string;
}

export function Tabs({
  tabs,
  active,
  onChange,
  label,
  children,
}: {
  tabs: readonly TabDef[];
  active: string;
  onChange: (id: string) => void;
  label: string;
  children: ReactNode;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});
  const onKey = (e: KeyboardEvent<HTMLDivElement>) => {
    const i = tabs.findIndex((t) => t.id === active);
    let next: number;
    if (e.key === "ArrowRight") next = (i + 1) % tabs.length;
    else if (e.key === "ArrowLeft") next = (i - 1 + tabs.length) % tabs.length;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = tabs.length - 1;
    else return;
    e.preventDefault();
    const id = tabs[next]?.id;
    if (id) {
      onChange(id);
      refs.current[id]?.focus();
    }
  };
  return (
    <div>
      <div className="no-print border-b">
        <div role="tablist" aria-label={label} className="flex flex-wrap gap-x-1" onKeyDown={onKey}>
          {tabs.map((t) => {
            const selected = t.id === active;
            return (
              <button
                key={t.id}
                ref={(el) => {
                  refs.current[t.id] = el;
                }}
                role="tab"
                type="button"
                id={`tab-${t.id}`}
                aria-selected={selected}
                aria-controls={`panel-${t.id}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => onChange(t.id)}
                className={cx(
                  "-mb-px cursor-pointer whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium",
                  selected
                    ? "border-foreground text-foreground"
                    : "border-transparent text-muted-foreground hover:text-foreground",
                )}
              >
                {t.label}
                {t.badge ? <span className="ml-1.5 rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{t.badge}</span> : null}
              </button>
            );
          })}
        </div>
      </div>
      <div role="tabpanel" id={`panel-${active}`} aria-labelledby={`tab-${active}`} tabIndex={0} className="pt-5 focus-visible:outline-none">
        {children}
      </div>
    </div>
  );
}
