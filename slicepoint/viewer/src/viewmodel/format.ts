// Number and text formatting shared by the view-models. Mirrors the helpers in
// slicepoint_core/report.py (_pct, _mm, _num) so the viewer and the HTML report agree.

const intFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const twoDp = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const oneDp = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export const NA = "n/a";

/** A share in [0, 1] as a percentage: 0.857 -> "86%". */
export function pct(v: number | null | undefined, dp = 0): string {
  return v === null || v === undefined || !Number.isFinite(v) ? NA : `${(100 * v).toFixed(dp)}%`;
}

/** Millimetres: 2.345 -> "2.3 mm"; signed -> "+2.3 mm". */
export function mm(v: number | null | undefined, dp = 1, signed = false): string {
  if (v === null || v === undefined || !Number.isFinite(v)) return NA;
  const text = v.toFixed(dp);
  return `${signed && v >= 0 ? "+" : ""}${text} mm`;
}

/** Integer with thousands separators. */
export function int(v: number): string {
  return intFmt.format(v);
}

/** Python's `:.3g` (trailing zeros stripped). */
function threeSig(v: number): string {
  let s = v.toPrecision(3);
  if (s.includes("e")) {
    const [m, e] = s.split("e") as [string, string];
    const mant = m.includes(".") ? m.replace(/\.?0+$/, "") : m;
    const exp = Number(e);
    return `${mant}e${exp < 0 ? "-" : "+"}${String(Math.abs(exp)).padStart(2, "0")}`;
  }
  if (s.includes(".")) s = s.replace(/\.?0+$/, "");
  return s;
}

/** A generic evidence value, as report.py `_num` prints it. */
export function num(v: unknown): string {
  if (v === null || v === undefined) return NA;
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") {
    if (!Number.isFinite(v)) return NA;
    if (Number.isInteger(v) && Math.abs(v) < 1e6) return intFmt.format(v);
    return Math.abs(v) < 1 ? threeSig(v) : twoDp.format(v);
  }
  return String(v);
}

/**
 * Effective n: whole -> "32", otherwise one decimal -> "31.4" (report.py
 * `format_n_effective`).
 */
export function formatNEffective(v: number): string {
  const text = oneDp.format(v);
  return text.endsWith(".0") ? text.slice(0, -2) : text;
}

/** "2026-11-09T19:24:05.12+00:00" -> "2026-11-09 19:24 UTC" (always UTC, never the viewer's locale). */
export function formatTimestamp(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
}

export function plural(n: number, one: string, many = `${one}s`): string {
  return `${int(n)} ${n === 1 ? one : many}`;
}

/** "a, b and c". */
export function joinAnd(items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}
