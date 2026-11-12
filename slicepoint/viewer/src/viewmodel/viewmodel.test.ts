import { describe, expect, it } from "vitest";
import { findSample } from "../fixtures";
import { findFixture } from "../fixtures/all";
import {
  buildViewModel,
  displaySiteName,
  filterCases,
  formatNEffective,
  humanizeColumn,
  humanizeEvidenceKey,
  loadResultData,
  loadResultText,
  readable,
  sortCases,
  type AssessmentResult,
} from ".";

/** A validated fixture, deep-copied so a test can change it. */
function fixture(id: string): AssessmentResult {
  const out = loadResultData(findFixture(id)?.data);
  if (!out.ok) throw new Error(out.error.title);
  return structuredClone(out.result);
}

describe("labels", () => {
  it("humanizes evidence keys", () => {
    expect(humanizeEvidenceKey("scans_with_near_duplicate")).toBe("Scans with near duplicate");
    expect(humanizeEvidenceKey("tvd.contrast_phase")).toBe("TVD · Contrast phase");
    expect(humanizeEvidenceKey("duplicates_under_different_patient_ids")).toBe("Duplicates under different patient IDs");
    expect(humanizeEvidenceKey("by_person_r2")).toBe("By person R2");
  });

  it("humanizes columns with the report.py label map", () => {
    expect(humanizeColumn("contrast_phase")).toBe("Contrast phase");
    expect(humanizeColumn("scanner_vendor")).toBe("Scanner brand");
    expect(humanizeColumn("age_band")).toBe("Age group");
    expect(humanizeColumn("some_new-column")).toBe("Some new column");
  });

  it("rewrites subgroup references", () => {
    expect(readable("contrast_phase=arterial (n=16)")).toBe("Contrast phase: arterial (16 cases)");
    expect(readable("in: sex=F (n=1), age_band=70-79.")).toBe("in: Sex: F (1 case), Age group: 70-79.");
    expect(readable("scanner_vendor=MISSING")).toBe("Scanner brand: missing");
    expect(readable("custom_col=x (n=3)")).toBe("Custom col: x (3 cases)");
    // Not a data column and no n: left alone.
    expect(readable("p=0.004 and auc=0.85")).toBe("p=0.004 and auc=0.85");
  });

  it("rewrites Python dict literals like report.py", () => {
    expect(readable("most often in: {'sex': {'F': 0.117}, 'contrast_phase': {'arterial': 0.1875}}.")).toBe(
      "most often in: sex F 12%; contrast phase arterial 19%.",
    );
    expect(readable("{'a': 1, 'b': 1.0}")).toBe("a 1; b 100%");
    expect(readable("{'broken': ")).toBe("{'broken': ");
  });

  it("formats effective n: whole numbers plain, else one decimal", () => {
    expect(formatNEffective(32)).toBe("32");
    expect(formatNEffective(32.0)).toBe("32");
    expect(formatNEffective(31.44)).toBe("31.4");
    expect(formatNEffective(1234.5)).toBe("1,234.5");
  });

  it("uses site_name, else the humanized site id", () => {
    expect(displaySiteName("hospital_b", null)).toBe("Hospital B");
    expect(displaySiteName("st-marys_east")).toBe("St Marys East");
    expect(displaySiteName("hospital_b", "  St. Mary's  ")).toBe("St. Mary's");
    expect(displaySiteName("hospital_b", " ")).toBe("Hospital B");
  });
});

describe("verdict", () => {
  it("shows the derived outcome when there is no override", () => {
    const vm = buildViewModel(fixture("hospital_b"), { showScores: false });
    expect(vm.verdict.final.label).toBe("NO-GO");
    expect(vm.verdict.override).toBeNull();
    expect(vm.verdict.problems.map((p) => p.title)).toEqual(["Different people", "AI accuracy"]);
    expect(vm.verdict.sentence).toMatch(/^2 of 5 checks found a problem/);
  });

  it("shows the override's final outcome with who, when and why", () => {
    const vm = buildViewModel(fixture("hospital_a_override"), { showScores: false });
    expect(vm.verdict.final.label).toBe("GO");
    expect(vm.verdict.derived.label).toBe("BORDERLINE");
    expect(vm.verdict.override).toMatchObject({
      by: "AI governance committee (example)",
      at: "2026-11-09 15:30 UTC",
      derived: { label: "BORDERLINE" },
      final: { label: "GO" },
    });
    expect(vm.verdict.override?.note).toMatch(/supervised pilot/);
    expect(vm.header.site).toBe("Hospital A (example committee override)");
  });

  it("names checks that were not evaluated and never treats them as passed", () => {
    const r = fixture("hospital_a_self");
    r.checks = r.checks.map((c) => (c.check_id === "repeats" ? { check_id: "repeats", state: "skipped", reason: "no embeddings" } : c)) as typeof r.checks;
    r.verdict.results = r.verdict.results.filter((x) => x.check_id !== "repeats");
    r.verdict.not_evaluated = ["repeats"];
    expect(loadResultData(r).ok).toBe(true);
    const vm = buildViewModel(r, { showScores: false });
    const card = vm.checks.find((c) => c.id === "repeats");
    expect(card?.status.label).toBe("Not evaluated");
    expect(card?.reason).toBe("no embeddings");
    expect(vm.verdict.counts.notEvaluated).toBe(1);
    expect(vm.verdict.sentence).toMatch(/Different people could not be evaluated/);
  });
});

describe("check cards", () => {
  it("formats n and effective n", () => {
    const vm = buildViewModel(fixture("hospital_b"), { showScores: false });
    const repeats = vm.checks.find((c) => c.id === "repeats");
    expect(repeats?.nLine).toBe("Based on 80 scans from 40 people; effective n 32.");
    expect(repeats?.failing.map((f) => f.title)).toEqual(["People", "Random vs by-person split leakage"]);
    expect(repeats?.subFactors.find((s) => s.id === "scans")?.failing).toBe(false);
  });

  it("groups evidence under the finding it belongs to", () => {
    const vm = buildViewModel(fixture("hospital_c"), { showScores: false });
    const scanning = vm.checks.find((c) => c.id === "scanning");
    const auc = scanning?.evidence.find((g) => g.factor === "scan_content_auc");
    expect(auc?.status.label).toBe("Problem");
    expect(auc?.rows.map((r) => [r.label, r.value])).toEqual([
      ["AUC", "0.847"],
      ["AUC raw", "0.847"],
    ]);
    expect(auc?.rows[0]?.key).toBe("scan_content_auc.auc");
    expect(scanning?.otherEvidence.map((r) => r.key)).toContain("tvd.contrast_phase");
  });

  it("renders a check that is not one of the default five", () => {
    const r = fixture("hospital_c");
    delete r.check_descriptors; // a file written before core 0.2.1: no descriptor for the new check
    r.checks = [...r.checks, { check_id: "contrast_timing", state: "evaluated", reason: null }] as typeof r.checks;
    r.verdict.results = [
      ...r.verdict.results,
      {
        check_id: "contrast_timing",
        status: "watch",
        n: 42,
        n_effective: 40.25,
        n_effective_method: "kish_design_effect_per_person",
        failing_sub_factors: ["late_bolus"],
        summary: "Bolus timing differs in sex=F (n=12).",
        evidence: [{ key: "late_bolus", value: "yellow", text: "Late bolus in contrast_phase=arterial (n=9)." }],
      },
    ];
    expect(loadResultData(r).ok).toBe(true);
    const vm = buildViewModel(r, { showScores: false });
    const card = vm.checks.find((c) => c.id === "contrast_timing");
    expect(card).toBeDefined();
    expect(card?.known).toBe(false);
    expect(card?.title).toBe("Contrast timing");
    expect(card?.status.label).toBe("Watch");
    expect(card?.nLine).toBe("Based on 42 scans; effective n 40.3.");
    expect(card?.failing).toEqual([{ id: "late_bolus", title: "Late bolus", failing: true }]);
    expect(card?.findings[0]?.text).toBe("Late bolus in Contrast phase: arterial (9 cases).");
    expect(card?.means).toBe("This check needs a closer look before deciding.");
  });
});

describe("check descriptors from the result", () => {
  it("takes titles and sub-factor titles from the result's descriptors", () => {
    const r = fixture("hospital_b");
    r.check_descriptors = (r.check_descriptors ?? []).map((d) =>
      d.id === "repeats"
        ? { ...d, title: "Distinct patients", sub_factors: (d.sub_factors ?? []).map((s) => ({ ...s, title: `${s.title} (result)` })) }
        : d,
    );
    const vm = buildViewModel(r, { showScores: false });
    const repeats = vm.checks.find((c) => c.id === "repeats");
    expect(repeats?.title).toBe("Distinct patients");
    expect(repeats?.failing.map((f) => f.title)).toEqual(["People (result)", "Random vs by-person split leakage (result)"]);
    // The viewer-only copy is kept for a built-in check.
    expect(repeats?.asks).toMatch(/^Does each scan come from a different person/);
    expect(vm.verdict.problems.find((p) => p.id === "repeats")?.title).toBe("Distinct patients");
    expect(vm.about.thresholds.kind === "ok" && vm.about.thresholds.targets.map((t) => t.label)).toContain("Distinct patients");
  });

  it("falls back to the built-in copy for a file without descriptors", () => {
    const withDescriptors = buildViewModel(fixture("hospital_b"), { showScores: false });
    const r = fixture("hospital_b");
    delete r.check_descriptors;
    expect(loadResultData(r).ok).toBe(true);
    const without = buildViewModel(r, { showScores: false });
    expect(without.checks.map((c) => [c.title, c.known, c.failing.map((f) => f.title)])).toEqual(
      withDescriptors.checks.map((c) => [c.title, c.known, c.failing.map((f) => f.title)]),
    );
    expect(without.checks.map((c) => c.title)).toEqual([
      "Different people",
      "Scan settings match",
      "Patients match",
      "Labels follow 30 mm rule",
      "AI accuracy",
    ]);
  });

  it("renders a new check from its descriptor alone", () => {
    const r = fixture("hospital_c");
    r.check_descriptors = [
      ...(r.check_descriptors ?? []),
      {
        id: "contrast_timing",
        title: "Contrast timing",
        definition: "Is the contrast bolus timed like at the reference?",
        sub_factors: [{ id: "late_bolus", title: "Bolus arrives late" }],
      },
    ];
    r.checks = [...r.checks, { check_id: "contrast_timing", state: "evaluated", reason: null }] as typeof r.checks;
    r.verdict.results = [
      ...r.verdict.results,
      {
        check_id: "contrast_timing",
        status: "watch",
        n: 42,
        failing_sub_factors: ["late_bolus"],
        summary: "Late bolus.",
        evidence: [{ key: "late_bolus", value: "yellow", text: "Late bolus." }],
      },
    ];
    expect(loadResultData(r).ok).toBe(true);
    const card = buildViewModel(r, { showScores: false }).checks.find((c) => c.id === "contrast_timing");
    expect(card?.known).toBe(true);
    expect(card?.asks).toBe("Is the contrast bolus timed like at the reference?");
    expect(card?.failing).toEqual([{ id: "late_bolus", title: "Bolus arrives late", failing: true }]);
    expect(card?.evidence[0]?.title).toBe("Bolus arrives late");
    expect(card?.means).toBe("This check needs a closer look before deciding.");
  });
});

describe("domain AUC and self-comparison", () => {
  it("shows the floored AUC and keeps the raw one", () => {
    const scanning = buildViewModel(fixture("hospital_b"), { showScores: false }).checks.find((c) => c.id === "scanning");
    const auc = scanning?.evidence.find((g) => g.factor === "scan_content_auc");
    expect(auc?.rows.find((r) => r.key === "scan_content_auc.auc")?.value).toBe("0.5");
    expect(Number(auc?.rows.find((r) => r.key === "scan_content_auc.auc_raw")?.value)).toBeLessThan(0.5);
    expect(auc?.text).toMatch(/no better than chance/);
  });

  it("flags a site compared with its own reference next to the verdict", () => {
    const own = buildViewModel(fixture("hospital_a_self"), { showScores: false });
    expect(own.verdict.selfComparison).toMatch(/compared against its own reference data/);
    expect(own.about.notes[0]).toBe(own.verdict.selfComparison);
    expect(own.verdict.derivedOutcome).toBe("borderline"); // the verdict is unchanged
    for (const id of ["hospital_b", "hospital_c", "hospital_d", "hospital_e"]) {
      expect(buildViewModel(fixture(id), { showScores: false }).verdict.selfComparison).toBeNull();
    }
  });
});

describe("provisional scores", () => {
  it("are unavailable and never shown when the file has none", () => {
    const vm = buildViewModel(fixture("hospital_c"), { showScores: true });
    expect(vm.scores).toEqual({ available: false, shown: false, methods: [] });
    expect(vm.checks.every((c) => c.score === null)).toBe(true);
    expect(vm.checks.flatMap((c) => c.otherEvidence).some((r) => r.key === "score_basis")).toBe(false);
  });

  it("are hidden by default even when the file has them", () => {
    const vm = buildViewModel(fixture("hospital_c_scores"), { showScores: false });
    expect(vm.scores.available).toBe(true);
    expect(vm.scores.shown).toBe(false);
    expect(vm.checks.every((c) => c.score === null)).toBe(true);
    const keys = vm.checks.flatMap((c) => [...c.otherEvidence, ...c.evidence.flatMap((g) => g.rows)]).map((r) => r.key);
    expect(keys.some((k) => k === "score_basis" || k.startsWith("score_part."))).toBe(false);
  });

  it("show the file's own score and method when switched on", () => {
    const vm = buildViewModel(fixture("hospital_c_scores"), { showScores: true });
    expect(vm.scores).toEqual({ available: true, shown: true, methods: ["provisional-v0"] });
    const scanning = vm.checks.find((c) => c.id === "scanning");
    expect(scanning?.score).toMatchObject({ display: "11", method: "provisional-v0", target: 70 });
  });
});

describe("optional blocks", () => {
  it("says 'not recorded in this result' instead of assuming defaults", () => {
    const r = fixture("hospital_b");
    delete r.thresholds;
    delete r.strata;
    delete r.cases_to_review;
    delete r.site_name;
    r.performance = {};
    expect(loadResultData(r).ok).toBe(true);
    const vm = buildViewModel(r, { showScores: false });
    expect(vm.strata).toEqual({ kind: "not_recorded", message: "No by-group table: not recorded in this result." });
    expect(vm.cases).toEqual({ kind: "not_recorded", message: "No cases-to-review list: not recorded in this result." });
    expect(vm.about.thresholds.kind).toBe("not_recorded");
    expect(vm.about.methods.join(" ")).toMatch(/By-group suppression rules: not recorded in this result/);
    expect(vm.performance.binary).toMatchObject({ kind: "missing" });
    expect(vm.performance.diameter.kind).toBe("missing");
    expect(vm.performance.dice.kind).toBe("missing");
    expect(vm.header.site).toBe("Hospital B");
  });

  it("says Dice markers are not recorded when the profile lacks them", () => {
    const r = fixture("hospital_b");
    if (r.thresholds) r.thresholds.dice_markers = null;
    const vm = buildViewModel(r, { showScores: false });
    expect(vm.performance.dice).toMatchObject({ kind: "ok", markers: null, markersNote: "Dice markers not recorded in this result." });
  });
});

describe("cases to review", () => {
  const vm = buildViewModel(fixture("hospital_b"), { showScores: false });
  if (vm.cases.kind !== "ok") throw new Error("expected cases");
  const rows = vm.cases.rows;

  it("keeps the producer's order and spells out reasons", () => {
    expect(rows.map((r) => r.priority)).toEqual([...rows.map((r) => r.priority)].sort((a, b) => a - b));
    expect(rows.find((r) => r.reasons.includes("size_error"))?.why.join(" ")).toMatch(/Size off by [+-]\d+\.\d mm \(tolerance 3 mm\)/);
  });

  it("sorts by size difference with missing errors last", () => {
    const sorted = sortCases(rows, "error", "desc");
    const errs = sorted.map((r) => r.absErrorMm);
    const present = errs.filter((e): e is number => e !== null);
    expect(present).toEqual([...present].sort((a, b) => b - a));
    expect(errs.slice(present.length).every((e) => e === null)).toBe(true);
  });

  it("filters by reason and by id", () => {
    expect(filterCases(rows, { reason: "no_answer", query: "" }).every((r) => r.reasons.includes("no_answer"))).toBe(true);
    const first = rows[0];
    if (!first) throw new Error("no rows");
    expect(filterCases(rows, { reason: "all", query: first.caseId.slice(0, 6).toUpperCase() }).map((r) => r.caseId)).toContain(first.caseId);
  });
});

describe("loading", () => {
  const good = JSON.stringify(findSample("hospital_b")?.data);

  it("refuses an unknown schema_version by name", () => {
    const out = loadResultText(good.replace('"schema_version":"0.1.0"', '"schema_version":"0.2.0"'));
    expect(out.ok).toBe(false);
    if (!out.ok) {
      expect(out.error.title).toBe('Unsupported schema version "0.2.0"');
      expect(out.error.detail).toMatch(/reads SlicePoint results with schema_version "0.1.0"/);
    }
  });

  it("explains invalid JSON, empty files and other file kinds", () => {
    const bad = loadResultText("{ not json");
    expect(!bad.ok && bad.error.title).toBe("This file is not valid JSON");
    const empty = loadResultText("  ");
    expect(!empty.ok && empty.error.title).toBe("The file is empty");
    const list = loadResultText("[1,2]");
    expect(!list.ok && list.error.detail).toMatch(/a list/);
    const poc = loadResultText(JSON.stringify({ hospital: "Hospital B", findings: [] }));
    expect(!poc.ok && poc.error.detail).toMatch(/proof-of-concept file/);
    const other = loadResultText(JSON.stringify({ result_type: "slicepoint.other", verdict: {} }));
    expect(!other.ok && other.error.detail).toMatch(/result_type is "slicepoint.other"/);
  });

  it("lists schema violations with readable paths", () => {
    const data = JSON.parse(good) as Record<string, unknown>;
    data.site_id = "Hospital B!";
    (data.verdict as Record<string, unknown>).outcome = "maybe";
    delete data.generator;
    data.extra_field = 1;
    const out = loadResultData(data);
    expect(out.ok).toBe(false);
    if (!out.ok) {
      expect(out.error.title).toBe("This result does not match the SlicePoint contract");
      const text = out.error.problems.join("\n");
      expect(text).toMatch(/the file: missing required field "generator"/);
      expect(text).toMatch(/the file: unexpected field "extra_field"/);
      expect(text).toMatch(/verdict\.outcome: must be one of "go", "no_go", "borderline"/);
      expect(text).toMatch(/site_id: must match pattern/);
    }
  });

  it("requires a time zone on timestamps", () => {
    const data = JSON.parse(good) as Record<string, unknown>;
    data.generated_at = "2026-11-09T10:00:00";
    const out = loadResultData(data);
    expect(!out.ok && out.error.problems.join(" ")).toMatch(/generated_at: must be a valid date-time with a time zone/);
  });

  it("does not modify the input", () => {
    const data = JSON.parse(good) as Record<string, unknown>;
    const before = JSON.stringify(data);
    loadResultData(data);
    expect(JSON.stringify(data)).toBe(before);
  });
});

describe("datasheet", () => {
  it("is absent when the run had no datasheet", () => {
    expect(buildViewModel(fixture("hospital_b"), { showScores: false }).datasheet.kind).toBe("none");
  });

  it("lists findings worst first and counts the flagged ones", () => {
    const v = buildViewModel(fixture("hospital_d"), { showScores: false }).datasheet;
    if (v.kind !== "ok") throw new Error("expected a datasheet section");
    expect(v.datasheetId).toBe("aaa-baseline-v0");
    expect(v.rows[0]?.status.label).toBe("Differs");
    expect(v.rows.at(-1)?.status.label).toBe("Similar");
    expect(v.flagged).toBe(v.rows.filter((r) => r.status.label === "Differs" || r.status.label === "Outside coverage").length);
    const sex = v.rows.find((r) => r.variable === "sex");
    expect(sex?.shares.map((s) => s.value).sort()).toEqual(["f", "m"]);
    expect(v.notes[0]).toMatch(/^TVD/);
  });

  it("does not change the verdict", () => {
    const r = fixture("hospital_d");
    const without = structuredClone(r);
    without.datasheet = null;
    expect(buildViewModel(r, { showScores: false }).verdict).toEqual(buildViewModel(without, { showScores: false }).verdict);
  });
});
