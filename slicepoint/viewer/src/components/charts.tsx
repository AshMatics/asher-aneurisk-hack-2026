// Small inline-SVG charts. Each has a text equivalent next to it (role="img" + label),
// and colours come from the theme tokens so they work in light and dark.
import type { CiPoint } from "../viewmodel";

const pctLabel = (v: number) => `${Math.round(v * 100)}%`;

/** Point-and-whisker rows on a 0-100% axis. */
export function CiChart({ rows, label }: { rows: readonly CiPoint[]; label: string }) {
  const left = 190;
  const width = 360;
  const rowH = 28;
  const top = 8;
  const h = top + rowH * rows.length + 26;
  const x = (v: number) => left + width * Math.max(0, Math.min(1, v));
  return (
    <svg viewBox={`0 0 ${left + width + 20} ${h}`} role="img" aria-label={label} className="h-auto w-full max-w-2xl">
      <title>{label}</title>
      {[0, 0.25, 0.5, 0.75, 1].map((t) => (
        <g key={t}>
          <line x1={x(t)} x2={x(t)} y1={top} y2={h - 22} className="stroke-border" strokeWidth={1} />
          <text x={x(t)} y={h - 8} textAnchor="middle" className="fill-muted-foreground text-[11px]">
            {pctLabel(t)}
          </text>
        </g>
      ))}
      {rows.map((r, i) => {
        const y = top + rowH * i + rowH / 2;
        return (
          <g key={r.label}>
            <text x={left - 10} y={y + 4} textAnchor="end" className="fill-foreground text-[12px]">
              {r.label}
            </text>
            {r.point === null || r.lo === null || r.hi === null ? (
              <text x={left + 6} y={y + 4} className="fill-muted-foreground text-[11px]">
                n/a
              </text>
            ) : (
              <>
                <line x1={x(r.lo)} x2={x(r.hi)} y1={y} y2={y} className="stroke-foreground" strokeWidth={2} />
                <line x1={x(r.lo)} x2={x(r.lo)} y1={y - 5} y2={y + 5} className="stroke-foreground" strokeWidth={2} />
                <line x1={x(r.hi)} x2={x(r.hi)} y1={y - 5} y2={y + 5} className="stroke-foreground" strokeWidth={2} />
                <circle cx={x(r.point)} cy={y} r={5} className="fill-chart-2" />
              </>
            )}
          </g>
        );
      })}
    </svg>
  );
}

/** A 0-100% bar with an optional target tick. */
export function ShareBar({ share, label, target }: { share: number | null; label: string; target?: number | null }) {
  const w = 260;
  const h = 16;
  const clamp = (v: number) => Math.max(0, Math.min(1, v));
  return (
    <svg viewBox={`0 0 ${w} ${h}`} role="img" aria-label={label} className="block h-4 w-full max-w-[260px]" preserveAspectRatio="none">
      <title>{label}</title>
      <rect x={0} y={2} width={w} height={h - 4} rx={3} className="fill-muted" />
      {share !== null ? <rect x={0} y={2} width={w * clamp(share)} height={h - 4} rx={3} className="fill-chart-2" /> : null}
      {target !== null && target !== undefined ? (
        <line x1={w * clamp(target)} x2={w * clamp(target)} y1={0} y2={h} className="stroke-foreground" strokeWidth={2} />
      ) : null}
    </svg>
  );
}

/** Dice on a 0.5-1.0 scale with the profile's markers (when the result records them). */
export function DiceGauge({
  median,
  mean,
  markers,
}: {
  median: number;
  mean: number;
  markers: { lower: number; upper: number } | null;
}) {
  const lo = 0.5;
  const left = 20;
  const width = 560;
  const h = 72;
  const x = (v: number) => left + (width * (Math.max(lo, Math.min(1, v)) - lo)) / (1 - lo);
  const label =
    `Dice median ${median.toFixed(3)}, mean ${mean.toFixed(3)}` +
    (markers ? `; markers at ${markers.lower.toFixed(2)} (basic) and ${markers.upper.toFixed(2)} (clinical)` : "");
  return (
    <svg viewBox={`0 0 ${left * 2 + width} ${h}`} role="img" aria-label={label} className="h-auto w-full max-w-2xl">
      <title>{label}</title>
      <rect x={left} y={22} width={width} height={12} rx={3} className="fill-muted" />
      {[0.5, 0.6, 0.7, 0.8, 0.9, 1].map((t) => (
        <text key={t} x={x(t)} y={52} textAnchor="middle" className="fill-muted-foreground text-[11px]">
          {t.toFixed(1)}
        </text>
      ))}
      <rect x={left} y={22} width={x(median) - left} height={12} rx={3} className="fill-chart-2" />
      {markers
        ? (
            [
              [markers.lower, "basic"],
              [markers.upper, "clinical"],
            ] as const
          ).map(([v, name]) => (
            <g key={name}>
              <line x1={x(v)} x2={x(v)} y1={16} y2={40} className="stroke-foreground" strokeWidth={2} />
              <text x={x(v)} y={12} textAnchor={name === "clinical" ? "end" : "middle"} className="fill-muted-foreground text-[11px]">
                {name} {v.toFixed(2)}
              </text>
            </g>
          ))
        : null}
      <circle cx={x(mean)} cy={28} r={5} className="fill-background stroke-foreground" strokeWidth={2} />
      <text x={left} y={68} className="fill-muted-foreground text-[11px]">
        bar = median {median.toFixed(3)}; ring = mean {mean.toFixed(3)}
        {Math.min(median, mean) < lo ? "; values under 0.5 sit at the left edge" : ""}
      </text>
    </svg>
  );
}
