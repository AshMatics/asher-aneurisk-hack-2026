// The vendor-datasheet section (result.datasheet), as slicepoint-core recorded it. A separate
// section: it never changes the verdict. Nothing is recomputed; rows are ordered by status.
import type { DatasheetComparison, DatasheetFindingStatus, VariableComparison } from "../contract";
import { pct } from "./format";
import { humanizeColumn } from "./labels";
import type { StatusLabel } from "./status";

export const DATASHEET_STATUS: Readonly<Record<DatasheetFindingStatus, StatusLabel>> = {
  outside_coverage: { tone: "problem", label: "Outside coverage", glyph: "✕" },
  differs: { tone: "watch", label: "Differs", glyph: "!" },
  differs_expected: { tone: "skip", label: "Differs (expected)", glyph: "~" },
  similar: { tone: "ok", label: "Similar", glyph: "✓" },
  not_testable: { tone: "skip", label: "Not testable", glyph: "–" },
};

const ORDER: readonly DatasheetFindingStatus[] = ["outside_coverage", "differs", "differs_expected", "similar", "not_testable"];

export const DATASHEET_LEAD =
  "This section does not change the verdict. It tests your scans against what the vendor discloses about its data: " +
  "coverage asks whether your scans are inside what the model saw, distribution whether they are spread the same way. " +
  "Only the datasheet's summary numbers are used.";

export const TVD_SMD_LEGEND =
  "TVD (total variation distance) is the share of scans that would have to change group for the two mixes to match: " +
  "0 is identical, 1 is nothing in common. SMD is the difference in means in standard deviations. A variable differs " +
  "only when the gap is both larger than the minimum and unlikely to be chance.";

export interface ShareRowView {
  readonly value: string;
  readonly site: string;
  readonly datasheet: string;
}

export interface DatasheetRowView {
  readonly variable: string;
  readonly label: string;
  readonly status: StatusLabel;
  readonly nSite: number;
  readonly nDatasheet: string;
  readonly detail: string;
  readonly shares: readonly ShareRowView[];
}

export type DatasheetView =
  | { readonly kind: "none" }
  | {
      readonly kind: "ok";
      readonly title: string;
      readonly datasheetId: string;
      readonly model: string;
      readonly describes: string;
      readonly scope: string;
      readonly scopeBroader: boolean;
      readonly rows: readonly DatasheetRowView[];
      /** Variables that read outside coverage or differ. */
      readonly flagged: number;
      readonly notes: readonly string[];
    };

function shares(v: VariableComparison): ShareRowView[] {
  const eq = v.equality;
  if (!eq?.site_shares || !eq.datasheet_shares) return [];
  const site = eq.site_shares;
  const ds = eq.datasheet_shares;
  const keys = [...new Set([...Object.keys(ds), ...Object.keys(site)])];
  return keys.map((k) => ({ value: k, site: pct(site[k] ?? 0), datasheet: pct(ds[k] ?? 0) }));
}

function detail(v: VariableComparison): string {
  const how = v.value_source === "reported" || v.value_source === "computed" ? "" : ` (${v.value_source} values)`;
  const approx = v.equality?.approximate ? " Approximate." : "";
  return `${v.reason ?? ""}${how}${approx}`.trim();
}

export function buildDatasheet(d: DatasheetComparison | null | undefined): DatasheetView {
  if (!d) return { kind: "none" };
  const rows = [...d.variables]
    .sort((a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status))
    .map((v) => ({
      variable: v.variable,
      label: v.label ?? humanizeColumn(v.variable),
      status: DATASHEET_STATUS[v.status],
      nSite: v.n_site,
      nDatasheet: v.datasheet_n == null ? "not given" : String(v.datasheet_n),
      detail: detail(v),
      shares: shares(v),
    }));
  const notes: string[] = [TVD_SMD_LEGEND];
  if (d.site_columns_not_in_datasheet.length) {
    notes.push(`Your data has, but the datasheet does not disclose: ${d.site_columns_not_in_datasheet.map(humanizeColumn).join(", ")}`);
  }
  if (d.not_disclosed.length) notes.push(`The datasheet says it does not disclose: ${d.not_disclosed.join("; ")}`);
  notes.push(...(d.notes ?? []));
  return {
    kind: "ok",
    title: d.datasheet_title,
    datasheetId: d.datasheet_id,
    model: d.model_name,
    describes: d.describes,
    scope: d.scope,
    scopeBroader: d.scope_broader,
    rows,
    flagged: d.variables.filter((v) => v.status === "outside_coverage" || v.status === "differs").length,
    notes,
  };
}
