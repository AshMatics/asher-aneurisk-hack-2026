// The live viewer's only network code: a small fetch wrapper over slicepoint-api.
//
// Same-origin only (the page is served by the API, or by Vite's dev proxy). The browser
// holds an HttpOnly session cookie from POST /v1/session; this code never sees it and
// never stores the token. Every request carries X-SlicePoint-CSRF: 1, which the API
// requires for cookie-authenticated unsafe methods. Only the live build imports this
// file; the static build is checked to contain no fetch at all (scripts/check-build.mjs).
import type { components } from "./api.generated";

type S = components["schemas"];
export type SessionInfo = S["SessionInfo"];
export type JobSummary = S["JobSummary"];
export type JobRecord = S["JobRecord"];
export type JobStep = S["JobStep"];
export type JobState = S["JobState"];
export type StepStatus = S["StepStatus"];
export type JobAccepted = S["JobAccepted"];
export type ReferenceInfo = S["ReferenceInfo"];
export type AssessmentRequest = S["AssessmentRequest"];

export const CSRF_HEADER = "X-SlicePoint-CSRF";
const JOB_ID = /^[0-9a-f]{32}$/;

export class ApiError extends Error {
  readonly status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export interface ApiClient {
  getSession(): Promise<SessionInfo>;
  signIn(token: string): Promise<SessionInfo>;
  signOut(): Promise<void>;
  listJobs(): Promise<readonly JobSummary[]>;
  getJob(jobId: string): Promise<JobRecord>;
  listDatasets(): Promise<readonly string[]>;
  listReferences(): Promise<readonly ReferenceInfo[]>;
  submitAssessment(request: AssessmentRequest): Promise<JobAccepted>;
  /** The raw result JSON text; the caller validates it with viewmodel/load.ts. */
  getResultText(jobId: string): Promise<string>;
  reportUrl(jobId: string): string;
}

export interface ClientOptions {
  /** Called on a 401 from any route except sign-in (the session ended). */
  onUnauthorized?: () => void;
  fetchImpl?: typeof fetch;
}

/** A readable one-liner from a FastAPI error body (string detail or a 422 list). */
export function errorDetail(status: number, body: unknown): string {
  const detail = body && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length) {
    return detail
      .map((e: { loc?: unknown[]; msg?: string }) => {
        const where = (e.loc ?? []).filter((p) => p !== "body").join(".");
        return where ? `${where}: ${e.msg ?? "invalid"}` : (e.msg ?? "invalid");
      })
      .join("; ");
  }
  return `The service answered HTTP ${status}.`;
}

function jobPath(jobId: string): string {
  if (!JOB_ID.test(jobId)) throw new ApiError(400, "Not a job id.");
  return `/v1/assessments/${jobId}`;
}

export function createClient(opts: ClientOptions = {}): ApiClient {
  const doFetch: typeof fetch = opts.fetchImpl ?? ((input, init) => fetch(input, init));

  async function call(method: string, path: string, body?: unknown, signIn = false): Promise<Response> {
    const headers: Record<string, string> = { Accept: "application/json", [CSRF_HEADER]: "1" };
    const init: RequestInit = {
      method,
      headers,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      referrerPolicy: "no-referrer",
    };
    if (body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let res: Response;
    try {
      res = await doFetch(path, init);
    } catch {
      throw new ApiError(0, "The SlicePoint service could not be reached.");
    }
    if (res.ok) return res;
    let parsed: unknown = null;
    try {
      parsed = await res.json();
    } catch {
      // not JSON; fall back to the status line
    }
    if (res.status === 401 && !signIn) opts.onUnauthorized?.();
    throw new ApiError(res.status, errorDetail(res.status, parsed));
  }

  const json = async <T>(p: Promise<Response>): Promise<T> => (await (await p).json()) as T;

  return {
    getSession: () => json<SessionInfo>(call("GET", "/v1/session")),
    signIn: (token) => json<SessionInfo>(call("POST", "/v1/session", { token }, true)),
    signOut: async () => {
      await call("DELETE", "/v1/session");
    },
    listJobs: async () => (await json<S["JobList"]>(call("GET", "/v1/assessments"))).jobs,
    getJob: (jobId) => json<JobRecord>(call("GET", jobPath(jobId))),
    listDatasets: async () => (await json<S["DatasetList"]>(call("GET", "/v1/datasets"))).datasets,
    listReferences: async () => (await json<S["ReferenceList"]>(call("GET", "/v1/references"))).references,
    submitAssessment: (request) => json<JobAccepted>(call("POST", "/v1/assessments", request)),
    getResultText: async (jobId) => (await call("GET", `${jobPath(jobId)}/result`)).text(),
    reportUrl: (jobId) => `${jobPath(jobId)}/report.html`,
  };
}
