// Readable labels. Same behaviour as slicepoint_core/report.py: the label map and
// humanizer for data columns, the site name, and the rewriting of subgroup references
// (`contrast_phase=arterial (n=16)` -> `Contrast phase: arterial (16 cases)`) and Python
// dict literals in finding text. Display only; the stored text is never changed.
import { int, pct } from "./format";

/** The level a missing value takes in strata rows (slicepoint_core.stats.MISSING). */
export const MISSING = "MISSING";

export const GROUP_LABEL: Readonly<Record<string, string>> = {
  contrast_phase: "Contrast phase",
  slice_thickness_class: "Slice thickness",
  sex: "Sex",
  age_band: "Age group",
  scanner_vendor: "Scanner brand",
  aaa_size_class: "Aneurysm size class",
  patient_id: "Patient",
  case_id: "Case",
};

const ACRONYMS: ReadonlySet<string> = new Set([
  "auc", "tvd", "icc", "mae", "rmse", "loa", "sd", "hu", "kvp", "pca", "knn", "aaa", "ai", "id", "ids", "r2",
]);

/**
 * An evidence key for display: `scans_with_near_duplicate` -> "Scans with near duplicate",
 * `tvd.contrast_phase` -> "TVD · Contrast phase", `auc` -> "AUC". The raw key stays
 * available to the UI (as a tooltip) for anyone matching it against result.json.
 */
export function humanizeEvidenceKey(key: string): string {
  return key
    .split(".")
    .map((part) => {
      if (GROUP_LABEL[part] !== undefined) return GROUP_LABEL[part];
      const words = part.split(/[_-]/).filter((w) => w.length > 0);
      if (words.length === 0) return part;
      const out = words.map((w) => (ACRONYMS.has(w.toLowerCase()) ? w.toUpperCase().replace("IDS", "IDs") : w.toLowerCase()));
      const first = out[0] ?? "";
      out[0] = first === first.toLowerCase() ? first.charAt(0).toUpperCase() + first.slice(1) : first;
      return out.join(" ");
    })
    .join(" · ");
}

/** `contrast_phase` -> "Contrast phase" (label map), else `some_column_name` -> "Some column name". */
export function humanizeColumn(name: string): string {
  const known = GROUP_LABEL[name];
  if (known !== undefined) return known;
  const text = name
    .replace(/-/g, "_")
    .split("_")
    .filter((w) => w.length > 0)
    .join(" ");
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : name;
}

/** `site_name` when given, else the site id made readable (`hospital_b` -> "Hospital B"). */
export function displaySiteName(siteId: string, siteName?: string | null): string {
  if (siteName && siteName.trim()) return siteName.trim();
  const words = siteId.split(/[_-]+/).filter((w) => w.length > 0);
  const out = words.map((w) => (w.length === 1 ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1))).join(" ");
  return out || siteId;
}

/** A strata level for display: the missing marker reads "missing". */
export function displayLevel(level: string): string {
  return level === MISSING ? "missing" : level;
}

// `contrast_phase=arterial (n=16)` or `sex=F`, as the checks write subgroup names.
const GROUP_REF = /\b([a-z][a-z0-9]*(?:_[a-z0-9]+)*)=([^\s,;()]+)(?: \(n=(\d+)\))?/g;
// A Python dict literal, possibly one level nested: {'sex': {'F': 0.117}}.
const DICT_LITERAL = /\{'[^{}]*(?:\{[^{}]*\}[^{}]*)*\}/g;

function groupRef(match: string, col: string, levelIn: string, n: string | undefined): string {
  // Only known data columns, or any `name=level (n=k)`, are rewritten, so `p=0.004` stays.
  if (!(col in GROUP_LABEL) && n === undefined) return match;
  let level = levelIn;
  let tail = "";
  if (n === undefined && level.endsWith(".")) {
    level = level.slice(0, -1);
    tail = ".";
  }
  if (level === MISSING) level = "missing";
  let out = `${humanizeColumn(col)}: ${level}`;
  if (n !== undefined) {
    const k = Number(n);
    out += ` (${int(k)} case${k === 1 ? "" : "s"})`;
  }
  return out + tail;
}

const FLOAT_TAG = "\u0000float:";

/** Parse a Python dict literal of strings/numbers/booleans/None (nested one level). */
function parsePyDict(text: string): Record<string, unknown> | null {
  // Convert to JSON: single-quoted strings to double-quoted, True/False/None to JSON.
  let json = "";
  let i = 0;
  while (i < text.length) {
    const ch = text[i] as string;
    if (ch === "'") {
      let j = i + 1;
      let s = "";
      while (j < text.length && text[j] !== "'") {
        if (text[j] === "\\") return null;
        s += text[j];
        j += 1;
      }
      if (j >= text.length) return null;
      json += JSON.stringify(s);
      i = j + 1;
      continue;
    }
    const rest = text.slice(i);
    const word = /^(True|False|None)\b/.exec(rest);
    if (word) {
      json += word[1] === "True" ? "true" : word[1] === "False" ? "false" : "null";
      i += word[0].length;
      continue;
    }
    // Python keeps int and float apart (a float prints as a percentage); JSON does not,
    // so floats are carried through as tagged strings.
    const number = /^-?\d+(\.\d*)?([eE][-+]?\d+)?/.exec(rest);
    if (number && !/[\w.]/.test(json.slice(-1))) {
      json += number[1] !== undefined || number[2] !== undefined ? JSON.stringify(FLOAT_TAG + number[0]) : number[0];
      i += number[0].length;
      continue;
    }
    if (ch === '"') return null;
    json += ch;
    i += 1;
  }
  try {
    const value: unknown = JSON.parse(json);
    return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

function fmtDictValue(v: unknown): string {
  if (typeof v === "string" && v.startsWith(FLOAT_TAG)) return pct(Number(v.slice(FLOAT_TAG.length)));
  if (v === true) return "True";
  if (v === false) return "False";
  if (v === null) return "None";
  return String(v);
}

function dictLiteral(match: string): string {
  const value = parsePyDict(match);
  if (value === null) return match;
  const parts: string[] = [];
  for (const [k, v] of Object.entries(value)) {
    if (v !== null && typeof v === "object" && !Array.isArray(v)) {
      const inner = Object.entries(v as Record<string, unknown>)
        .map(([kk, vv]) => `${kk} ${fmtDictValue(vv)}`)
        .join(", ");
      parts.push(`${(GROUP_LABEL[k] ?? k).toLowerCase()} ${inner}`);
    } else {
      parts.push(`${k} ${fmtDictValue(v)}`);
    }
  }
  return parts.join("; ");
}

/**
 * Finding text made readable: Python dict literals become `sex F 12%`, subgroup
 * references become `Contrast phase: arterial (16 cases)`.
 */
export function readable(text: string): string {
  return text.replace(DICT_LITERAL, dictLiteral).replace(GROUP_REF, groupRef);
}
