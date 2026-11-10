// Test-only: a job factory and a fake slicepoint-api behind a mocked fetch.
import { vi } from "vitest";
import type { JobRecord, JobSummary } from "./client";

export function makeJob(over: Partial<JobRecord> = {}): JobRecord {
  return {
    job_id: "a".repeat(32),
    kind: "assessment",
    state: "running",
    created_at: "2026-11-10T08:00:00Z",
    request: {
      dataset: "hospital_b",
      site_id: "hospital_b",
      site_name: "Hospital B",
      reference_id: "ref-hospital_a",
      reference_dataset: null,
      reference_site_id: null,
      profile_id: "hackathon-default-v0",
      on_inconsistency: "raise",
      show_provisional_scores: false,
    },
    steps: [
      { id: "ingest_site", title: "Read the site data", status: "succeeded", duration_ms: 420, message: null },
      { id: "segmentation", title: "Segmentation", status: "skipped", message: "service not configured" },
      { id: "run_checks", title: "Run the checks", status: "running" },
      { id: "render_report", title: "Write the report", status: "pending" },
    ],
    audit: { requested_by: "unknown", api_version: "0.1.0", core_version: "0.2.0", schemas_version: "0.2.0" },
    ...over,
  };
}

export function summary(job: JobRecord): JobSummary {
  return {
    job_id: job.job_id,
    state: job.state,
    created_at: job.created_at,
    finished_at: job.finished_at ?? null,
    site_id: job.request.site_id,
    dataset: job.request.dataset,
    verdict: job.audit.verdict ?? null,
  };
}

export interface Call {
  method: string;
  path: string;
  headers: Record<string, string>;
  body: unknown;
  credentials: RequestCredentials | undefined;
}

type Handler = (call: Call) => { status?: number; body?: unknown; text?: string } | undefined;

export const TOKEN = "correct-horse-battery-staple-0123456789";

/**
 * A fake API. `routes` maps "METHOD /path" to a handler (or a list of answers served in
 * order, the last one repeating). Sign-in accepts TOKEN; the session is tracked.
 */
export function fakeApi(routes: Record<string, Handler | { status?: number; body?: unknown; text?: string }[]>, signedIn = false) {
  const calls: Call[] = [];
  const state = { signedIn };
  const counters: Record<string, number> = {};
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const method = init?.method ?? "GET";
    const path = String(input);
    const headers = { ...(init?.headers as Record<string, string>) };
    const body = typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
    const call: Call = { method, path, headers, body, credentials: init?.credentials };
    calls.push(call);
    const key = `${method} ${path}`;
    let answer: { status?: number; body?: unknown; text?: string } | undefined;
    const route = routes[key];
    if (Array.isArray(route)) {
      const i = counters[key] ?? 0;
      counters[key] = i + 1;
      answer = route[Math.min(i, route.length - 1)];
    } else if (route) {
      answer = route(call);
    } else if (key === "GET /v1/session") {
      answer = { body: { signed_in: state.signedIn, expires_at: null } };
    } else if (key === "POST /v1/session") {
      const ok = (body as { token?: string }).token === TOKEN;
      state.signedIn = ok;
      answer = ok ? { body: { signed_in: true, expires_at: "2026-11-10T16:00:00Z" } } : { status: 401, body: { detail: "Invalid token" } };
    } else if (key === "DELETE /v1/session") {
      state.signedIn = false;
      answer = { status: 204 };
    } else if (key === "GET /v1/datasets") {
      answer = { body: { datasets: ["hospital_a", "hospital_b"] } };
    } else if (key === "GET /v1/references") {
      answer = { body: { references: [] } };
    } else if (key === "GET /v1/assessments") {
      answer = { body: { jobs: [] } };
    }
    answer ??= { status: 404, body: { detail: "not found" } };
    const status = answer.status ?? 200;
    const text = answer.text ?? (answer.body === undefined ? null : JSON.stringify(answer.body));
    return new Response(status === 204 ? null : text, { status, headers: { "Content-Type": "application/json" } });
  });
  return { fetchImpl: fetchImpl as unknown as typeof fetch, calls, state };
}
