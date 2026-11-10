// Every bundled fixture validates against the contract schema and renders to a view-model.
import { describe, expect, it } from "vitest";
import { validate } from "../contract";
import { ALL_FIXTURES as SAMPLES } from "../fixtures/all";
import { buildViewModel, loadResultData } from ".";

const EXPECTED: Record<string, { derived: string; final: string }> = {
  hospital_b: { derived: "no_go", final: "no_go" },
  hospital_c: { derived: "no_go", final: "no_go" },
  hospital_d: { derived: "no_go", final: "no_go" },
  hospital_e: { derived: "no_go", final: "no_go" },
  hospital_a_self: { derived: "borderline", final: "borderline" },
  hospital_a_override: { derived: "borderline", final: "go" },
  hospital_c_scores: { derived: "no_go", final: "no_go" },
};

describe("bundled fixtures", () => {
  it("covers every sample", () => {
    expect(SAMPLES.map((s) => s.id).sort()).toEqual(Object.keys(EXPECTED).sort());
  });

  for (const sample of SAMPLES) {
    describe(sample.id, () => {
      it("validates against AssessmentResult.schema.json", () => {
        const ok = validate(sample.data);
        expect(validate.errors ?? []).toEqual([]);
        expect(ok).toBe(true);
      });

      it("loads and builds a complete view-model", () => {
        const out = loadResultData(sample.data);
        if (!out.ok) throw new Error(out.error.title + ": " + out.error.problems.join("; "));
        const vm = buildViewModel(out.result, { showScores: true, readNotes: out.compatNotes });
        expect(vm.verdict.derivedOutcome).toBe(EXPECTED[sample.id]?.derived);
        expect(vm.verdict.finalOutcome).toBe(EXPECTED[sample.id]?.final);
        expect(vm.checks.map((c) => c.id)).toEqual(["repeats", "scanning", "patients", "labels", "accuracy"]);
        expect(vm.checks.every((c) => c.known && c.status.label.length > 0)).toBe(true);
        expect(vm.strata.kind).toBe("ok");
        expect(vm.cases.kind).toBe("ok");
        expect(vm.about.thresholds.kind).toBe("ok");
        expect(vm.performance.dice.kind).toBe("ok");
        // Readable text: no raw subgroup references or Python dict literals in findings.
        for (const c of vm.checks) {
          for (const f of c.findings) {
            expect(f.text).not.toMatch(/\b(contrast_phase|sex|age_band|scanner_vendor)=/);
            expect(f.text).not.toMatch(/\{'/);
          }
        }
      });
    });
  }

  it("rejects the Pydantic field-name spelling of the Dice shares (the schema requires the alias)", () => {
    const data = structuredClone(SAMPLES[0]?.data) as { performance: { dice: Record<string, unknown> } };
    const dice = data.performance.dice;
    dice.share_below_0_90 = dice["share_below_0.90"];
    delete dice["share_below_0.90"];
    expect(loadResultData(data).ok).toBe(false);
  });
});
