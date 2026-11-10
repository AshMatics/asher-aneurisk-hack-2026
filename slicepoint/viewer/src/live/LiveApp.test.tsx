import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { findSample } from "../fixtures";
import { CSRF_HEADER } from "./client";
import { LiveApp } from "./LiveApp";
import { TOKEN, fakeApi, makeJob, summary } from "./test-helpers";

const JOB = "a".repeat(32);
const POLL = 15;
const hospitalB = findSample("hospital_b")?.data;

const running = makeJob();
const done = makeJob({
  state: "succeeded",
  finished_at: "2026-11-10T08:01:00Z",
  steps: [
    { id: "ingest_site", title: "Read the site data", status: "succeeded", duration_ms: 420 },
    { id: "segmentation", title: "Segmentation", status: "skipped", message: "service not configured" },
    { id: "run_checks", title: "Run the checks", status: "succeeded", duration_ms: 1500 },
    { id: "render_report", title: "Write the report", status: "succeeded", duration_ms: 30 },
  ],
  audit: { ...running.audit, verdict: "no_go" },
});

afterEach(() => vi.restoreAllMocks());

describe("LiveApp sign-in", () => {
  it("signs in with the token, clears the field and never stores the token", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    const api = fakeApi({});
    const user = userEvent.setup();
    render(<LiveApp fetchImpl={api.fetchImpl} pollMs={POLL} />);
    const field = await screen.findByLabelText("Service token");
    await user.type(field, TOKEN);
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Assessments" })).toBeInTheDocument();

    const post = api.calls.find((c) => c.method === "POST" && c.path === "/v1/session");
    expect(post?.body).toEqual({ token: TOKEN });
    expect(post?.headers[CSRF_HEADER]).toBe("1");
    expect(post?.credentials).toBe("same-origin");
    // The token went out once, in the sign-in body only, and was stored nowhere.
    const withToken = api.calls.filter((c) => JSON.stringify(c).includes(TOKEN));
    expect(withToken).toHaveLength(1);
    expect(api.calls.every((c) => !("Authorization" in c.headers))).toBe(true);
    expect(setItem.mock.calls.flat().join(" ")).not.toContain(TOKEN);
    expect(JSON.stringify({ ...window.localStorage })).not.toContain(TOKEN);
    expect(JSON.stringify({ ...window.sessionStorage })).not.toContain(TOKEN);
    expect(document.body.innerHTML).not.toContain(TOKEN);
  });

  it("clears the field and says so when the token is wrong", async () => {
    const api = fakeApi({});
    const user = userEvent.setup();
    render(<LiveApp fetchImpl={api.fetchImpl} pollMs={POLL} />);
    const field = await screen.findByLabelText<HTMLInputElement>("Service token");
    await user.type(field, "not-the-token");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That token was not accepted.");
    expect(field.value).toBe("");
    expect(screen.queryByRole("heading", { name: "Assessments" })).not.toBeInTheDocument();
  });

  it("signs out and returns to the sign-in screen", async () => {
    const api = fakeApi({}, true);
    const user = userEvent.setup();
    render(<LiveApp fetchImpl={api.fetchImpl} pollMs={POLL} />);
    await user.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByLabelText("Service token")).toBeInTheDocument();
    const del = api.calls.find((c) => c.method === "DELETE");
    expect(del?.path).toBe("/v1/session");
    expect(del?.headers[CSRF_HEADER]).toBe("1");
  });

  it("goes back to sign-in when the session expires", async () => {
    const api = fakeApi({ "GET /v1/assessments": [{ status: 401, body: { detail: "Invalid or missing bearer token" } }] }, true);
    render(<LiveApp fetchImpl={api.fetchImpl} pollMs={POLL} />);
    expect(await screen.findByLabelText("Service token")).toBeInTheDocument();
    expect(screen.getByText("Your session ended. Sign in again.")).toBeInTheDocument();
  });
});

describe("LiveApp jobs", () => {
  it("lists jobs and polls while one is active", async () => {
    const api = fakeApi({ "GET /v1/assessments": [{ body: { jobs: [summary(running)] } }, { body: { jobs: [summary(done)] } }] }, true);
    render(<LiveApp fetchImpl={api.fetchImpl} pollMs={POLL} />);
    const row = await screen.findByTestId(`job-${JOB}`);
    expect(within(row).getAllByText("hospital_b", { selector: "td" })).toHaveLength(2); // site and dataset
    expect(within(row).getByText("Running")).toBeInTheDocument();
    expect(within(row).getByText("none yet")).toBeInTheDocument();
    expect(within(row).getByText("2026-11-10 08:00 UTC")).toBeInTheDocument();
    // Polling picks up the finished job.
    await waitFor(() => expect(within(screen.getByTestId(`job-${JOB}`)).getByText("Finished")).toBeInTheDocument());
    const finished = screen.getByTestId(`job-${JOB}`);
    expect(within(finished).getByText("NO-GO")).toBeInTheDocument();
    expect(within(finished).getByRole("button", { name: /Open result/ })).toBeInTheDocument();
    const link = within(finished).getByRole("link", { name: /HTML report/ });
    expect(link).toHaveAttribute("href", `/v1/assessments/${JOB}/report.html`);
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
    // Nothing is active any more, so polling stops.
    const n = api.calls.filter((c) => c.path === "/v1/assessments").length;
    await new Promise((r) => setTimeout(r, POLL * 5));
    expect(api.calls.filter((c) => c.path === "/v1/assessments").length).toBe(n);
  });

  it("opens a finished job's result in the viewer, validated like a file", async () => {
    const api = fakeApi(
      {
        "GET /v1/assessments": [{ body: { jobs: [summary(done)] } }],
        [`GET /v1/assessments/${JOB}/result`]: [{ body: hospitalB }],
      },
      true,
    );
    const user = userEvent.setup();
    render(<LiveApp fetchImpl={api.fetchImpl} pollMs={POLL} />);
    await user.click(await screen.findByRole("button", { name: /Open result/ }));
    expect(await screen.findByRole("heading", { name: "SlicePoint fit check: Hospital B" })).toBeInTheDocument();
    expect(screen.getByTestId("final-verdict")).toHaveTextContent("NO-GO");
    expect(screen.getByRole("link", { name: /HTML report/ })).toHaveAttribute("href", `/v1/assessments/${JOB}/report.html`);
    await user.click(screen.getByRole("button", { name: "← All assessments" }));
    expect(await screen.findByRole("heading", { name: "Assessments" })).toBeInTheDocument();
  });

  it("refuses a result that does not match the contract", async () => {
    const api = fakeApi(
      {
        "GET /v1/assessments": [{ body: { jobs: [summary(done)] } }],
        [`GET /v1/assessments/${JOB}/result`]: [{ body: { ...(hospitalB as object), schema_version: "9.9" } }],
      },
      true,
    );
    const user = userEvent.setup();
    render(<LiveApp fetchImpl={api.fetchImpl} pollMs={POLL} />);
    await user.click(await screen.findByRole("button", { name: /Open result/ }));
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent('Unsupported schema version "9.9"');
    expect(screen.queryByTestId("final-verdict")).not.toBeInTheDocument();
  });
});

describe("LiveApp start form and progress", () => {
  it("requires the reference site id, then submits and follows the steps", async () => {
    const api = fakeApi(
      {
        "POST /v1/assessments": () => ({ status: 202, body: { job_id: JOB, state: "queued", status_url: "", result_url: "", report_url: "" } }),
        [`GET /v1/assessments/${JOB}`]: [{ body: running }, { body: done }],
      },
      true,
    );
    const user = userEvent.setup();
    render(<LiveApp fetchImpl={api.fetchImpl} pollMs={POLL} />);
    expect(await screen.findByRole("heading", { name: "Start an assessment" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Site dataset")).toHaveTextContent("hospital_b"));

    await user.selectOptions(screen.getByLabelText("Site dataset"), "hospital_b");
    await user.type(screen.getByLabelText("Site id"), "hospital_b");
    await user.click(screen.getByLabelText("Build from a reference dataset"));
    await user.selectOptions(screen.getByLabelText("Reference dataset"), "hospital_a");
    expect(screen.getByLabelText<HTMLInputElement>("Reference site id").value).toBe("");
    expect(screen.getByLabelText<HTMLInputElement>(/provisional 0-100 scores/)).not.toBeChecked();
    await user.click(screen.getByRole("button", { name: "Start assessment" }));
    expect(screen.getByText(/Enter the reference site id\. It is never guessed/)).toBeInTheDocument();
    expect(screen.getByLabelText("Reference site id")).toHaveAttribute("aria-invalid", "true");
    expect(api.calls.some((c) => c.method === "POST" && c.path === "/v1/assessments")).toBe(false);

    await user.type(screen.getByLabelText("Reference site id"), "hospital_a");
    await user.click(screen.getByRole("button", { name: "Start assessment" }));
    const post = api.calls.find((c) => c.method === "POST" && c.path === "/v1/assessments");
    expect(post?.body).toEqual({
      dataset: "hospital_b",
      site_id: "hospital_b",
      site_name: null,
      reference_dataset: "hospital_a",
      reference_site_id: "hospital_a",
      on_inconsistency: "raise",
      show_provisional_scores: false,
    });
    expect(post?.headers[CSRF_HEADER]).toBe("1");

    // Progress: a skipped step looks and reads differently from a finished one.
    expect(await screen.findByRole("heading", { name: "Assessment of Hospital B (hospital_b)" })).toBeInTheDocument();
    const skipped = screen.getByTestId("step-segmentation");
    const ran = screen.getByTestId("step-ingest_site");
    expect(skipped).toHaveAttribute("data-status", "Skipped, did not run");
    expect(within(skipped).getByText("service not configured")).toBeInTheDocument();
    expect(ran).toHaveAttribute("data-status", "Done");
    expect(skipped.className).toContain("border-dashed");
    expect(ran.className).not.toContain("border-dashed");
    expect(screen.getByText(/A skipped step did not run\. It is not a pass/)).toBeInTheDocument();
    expect(screen.getByTestId("step-run_checks")).toHaveAttribute("data-status", "Running");
    expect(screen.getByTestId("step-render_report")).toHaveAttribute("data-status", "Waiting");

    // Polling until done; then the result and report are offered.
    await waitFor(() => expect(screen.getByTestId("job-summary")).toHaveTextContent("4 steps: 3 done, 1 skipped."));
    expect(screen.getByTestId("step-segmentation")).toHaveAttribute("data-status", "Skipped, did not run");
    expect(screen.getByRole("button", { name: "Open result" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /HTML report/ })).toBeInTheDocument();
  });

  it("validates the site id and shows server rejections", async () => {
    const api = fakeApi(
      {
        "GET /v1/references": [{ body: { references: [{ reference_id: "ref-hospital_a", site_id: "hospital_a", dataset: "hospital_a", n_cases: 120, n_people: 100, has_labels: true, embedding_space_id: null, profile_id: "p", dataset_fingerprint: "x", built_at: "2026-11-10T08:00:00Z", built_by: "x" }] } }],
        "POST /v1/assessments": () => ({ status: 503, body: { detail: "too many jobs queued; retry later" } }),
      },
      true,
    );
    const user = userEvent.setup();
    render(<LiveApp fetchImpl={api.fetchImpl} pollMs={POLL} />);
    await waitFor(() => expect(screen.getByLabelText("Stored reference")).toHaveTextContent("ref-hospital_a (site hospital_a, 120 cases)"));
    await user.selectOptions(screen.getByLabelText("Site dataset"), "hospital_b");
    await user.type(screen.getByLabelText("Site id"), "Hospital B");
    await user.selectOptions(screen.getByLabelText("Stored reference"), "ref-hospital_a");
    await user.click(screen.getByRole("button", { name: "Start assessment" }));
    expect(screen.getByText(/Lower-case letters, digits/)).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Site id"));
    await user.type(screen.getByLabelText("Site id"), "hospital_b");
    await user.click(screen.getByLabelText(/provisional 0-100 scores/));
    await user.click(screen.getByRole("button", { name: "Start assessment" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("too many jobs queued; retry later");
    const post = api.calls.find((c) => c.method === "POST" && c.path === "/v1/assessments");
    expect(post?.body).toMatchObject({ reference_id: "ref-hospital_a", show_provisional_scores: true });
  });
});
