import { describe, expect, it } from "vitest";
import { errorDetail } from "./client";
import { makeJob } from "./test-helpers";
import { EMPTY_FORM, JOB_STATE, STEP_STATUS, anyActive, jobProgress, jobRows, validateStartForm } from "./viewmodel";

describe("start form validation", () => {
  const filled = { ...EMPTY_FORM, dataset: "hospital_b", siteId: "hospital_b", referenceId: "ref-hospital_a" };

  it("builds a stored-reference request with provisional scores off by default", () => {
    const out = validateStartForm({ ...filled, siteName: "  Hospital B " });
    expect(out).toEqual({
      ok: true,
      request: {
        dataset: "hospital_b",
        site_id: "hospital_b",
        site_name: "Hospital B",
        reference_id: "ref-hospital_a",
        on_inconsistency: "raise",
        show_provisional_scores: false,
      },
    });
  });

  it("requires everything and guesses nothing", () => {
    const out = validateStartForm(EMPTY_FORM);
    expect(out.ok).toBe(false);
    if (out.ok) return;
    expect(Object.keys(out.errors).sort()).toEqual(["dataset", "referenceId", "siteId"]);
    expect(out.errors.siteId).toMatch(/never guessed/);
  });

  it("requires the reference site id with a reference dataset", () => {
    const out = validateStartForm({ ...filled, referenceMode: "dataset", referenceDataset: "hospital_a" });
    expect(out.ok).toBe(false);
    if (!out.ok) expect(out.errors.referenceSiteId).toMatch(/reference site id.*never guessed/);
    const ok = validateStartForm({ ...filled, referenceMode: "dataset", referenceDataset: "hospital_a", referenceSiteId: "hospital_a" });
    expect(ok.ok && ok.request).toMatchObject({ reference_dataset: "hospital_a", reference_site_id: "hospital_a" });
    expect(ok.ok && "reference_id" in ok.request).toBe(false);
  });

  it("checks the site id pattern from the OpenAPI contract", () => {
    for (const bad of ["Hospital B", "-x", "a".repeat(65), "x/y"]) {
      const out = validateStartForm({ ...filled, siteId: bad });
      expect(out.ok, bad).toBe(false);
    }
    expect(validateStartForm({ ...filled, siteName: "x".repeat(201) }).ok).toBe(false);
  });
});

describe("job views", () => {
  it("never shows a skipped step like a passed one", () => {
    expect(STEP_STATUS.skipped.tone).not.toBe(STEP_STATUS.succeeded.tone);
    expect(STEP_STATUS.skipped.glyph).not.toBe(STEP_STATUS.succeeded.glyph);
    expect(STEP_STATUS.skipped.label).toMatch(/did not run/);
  });

  it("summarises progress", () => {
    const v = jobProgress(makeJob());
    expect(v.summary).toBe("4 steps: 1 done, 1 skipped, 1 running, 1 waiting.");
    expect(v.active).toBe(true);
    expect(v.canOpen).toBe(false);
    expect(v.anySkipped).toBe(true);
    expect(v.title).toBe("Hospital B (hospital_b)");
    expect(v.steps[0]?.duration).toBe("420 ms");
    expect(v.steps[1]).toMatchObject({ skipped: true, message: "service not configured" });
  });

  it("labels a finished job without implying a pass", () => {
    expect(JOB_STATE.succeeded.label).toBe("Finished");
    const rows = jobRows([
      { job_id: "b".repeat(32), state: "succeeded", created_at: "2026-11-10T08:00:00Z", finished_at: null, site_id: "hospital_b", dataset: "hospital_b", verdict: "no_go" },
      { job_id: "c".repeat(32), state: "queued", created_at: "2026-11-10T08:01:00Z", finished_at: null, site_id: "hospital_c", dataset: "hospital_c", verdict: null },
    ]);
    expect(rows[0]).toMatchObject({ canOpen: true, created: "2026-11-10 08:00 UTC" });
    expect(rows[0]?.verdict?.label).toBe("NO-GO");
    expect(rows[1]).toMatchObject({ canOpen: false, verdict: null });
    expect(anyActive([{ state: "succeeded" }, { state: "queued" }])).toBe(true);
    expect(anyActive([{ state: "succeeded" }, { state: "failed" }])).toBe(false);
  });
});

describe("errorDetail", () => {
  it("reads FastAPI errors", () => {
    expect(errorDetail(404, { detail: "job not found" })).toBe("job not found");
    expect(errorDetail(422, { detail: [{ loc: ["body", "site_id"], msg: "bad", type: "x" }] })).toBe("site_id: bad");
    expect(errorDetail(500, null)).toBe("The service answered HTTP 500.");
  });
});
