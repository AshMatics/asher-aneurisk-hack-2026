// Read a result file: parse, check the contract version, validate against the JSON Schema
// (a validator precompiled from slicepoint/schemas/jsonschema/AssessmentResult.schema.json),
// and turn every failure into a human-readable message. Pure TypeScript; no IO.
import { RESULT_TYPE, SCHEMA_VERSION, validate } from "../contract";
import type { AssessmentResult, ValidationError } from "../contract";

export interface LoadError {
  /** One line naming the problem. */
  readonly title: string;
  /** What to do about it. */
  readonly detail: string;
  /** Specific problems (for a schema failure: field path and message). */
  readonly problems: readonly string[];
}

export type LoadOutcome =
  | { readonly ok: true; readonly result: AssessmentResult; readonly compatNotes: readonly string[] }
  | { readonly ok: false; readonly error: LoadError };

/** Files larger than this are refused before reading (a result is ~100 kB). */
export const MAX_FILE_BYTES = 50 * 1024 * 1024;

const MAX_PROBLEMS = 8;

function fail(title: string, detail: string, problems: readonly string[] = []): LoadOutcome {
  return { ok: false, error: { title, detail, problems } };
}

function isObject(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

function readablePath(instancePath: string): string {
  if (!instancePath) return "the file";
  return instancePath
    .split("/")
    .slice(1)
    .map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"))
    .reduce((acc, part) => (/^\d+$/.test(part) ? `${acc}[${part}]` : acc ? `${acc}.${part}` : part), "");
}

function describe(e: ValidationError): string {
  const where = readablePath(e.instancePath);
  const p = e.params;
  switch (e.keyword) {
    case "required":
      return `${where}: missing required field "${String(p.missingProperty)}"`;
    case "additionalProperties":
      return `${where}: unexpected field "${String(p.additionalProperty)}"`;
    case "enum":
      return `${where}: must be one of ${(p.allowedValues as unknown[]).map((v) => JSON.stringify(v)).join(", ")}`;
    case "const":
      return `${where}: must be ${JSON.stringify(p.allowedValue)}`;
    case "type":
      return `${where}: must be ${String(p.type)}`;
    case "format":
      return `${where}: must be a valid ${String(p.format)}${p.format === "date-time" ? " with a time zone" : ""}`;
    default:
      return `${where}: ${e.message ?? e.keyword}`;
  }
}

/** Schema errors as short sentences. Drops the noise Ajv adds for nullable unions. */
export function describeSchemaErrors(errors: readonly ValidationError[]): string[] {
  const real = errors.filter((e) => e.keyword !== "anyOf" && e.keyword !== "if");
  const pathsWithOther = new Set(
    real.filter((e) => !(e.keyword === "type" && e.params.type === "null")).map((e) => e.instancePath),
  );
  const kept = real.filter(
    (e) => !(e.keyword === "type" && e.params.type === "null" && pathsWithOther.has(e.instancePath)),
  );
  const lines = [...new Set((kept.length ? kept : errors).map(describe))];
  if (lines.length > MAX_PROBLEMS) {
    return [...lines.slice(0, MAX_PROBLEMS), `... and ${lines.length - MAX_PROBLEMS} more`];
  }
  return lines;
}

function guessKind(data: Record<string, unknown>): string | null {
  if ("findings" in data && ("hospital" in data || "scans" in data)) {
    return "It looks like a proof-of-concept file (<hospital>_slicepoint.json). Open the result.json written by `slicepoint assess` instead.";
  }
  if ("triggers" in data && "check_targets" in data) {
    return "It looks like a threshold profile, not an assessment result.";
  }
  if ("reference_id" in data && !("verdict" in data)) {
    return "It looks like a reference profile (reference.json), not an assessment result.";
  }
  return null;
}

/** Validate an already-parsed value. */
export function loadResultData(input: unknown): LoadOutcome {
  if (!isObject(input)) {
    return fail(
      "This file is not a SlicePoint result",
      "A result is one JSON object. This file holds " + (Array.isArray(input) ? "a list" : `a ${typeof input}`) + ".",
    );
  }
  const resultType = input.result_type;
  if (resultType !== undefined && resultType !== RESULT_TYPE) {
    return fail(
      "This file is not a SlicePoint assessment result",
      `Its result_type is ${JSON.stringify(resultType)}; this viewer reads "${RESULT_TYPE}".`,
    );
  }
  if (resultType === undefined && !("verdict" in input)) {
    const hint = guessKind(input);
    return fail(
      "This file is not a SlicePoint assessment result",
      hint ?? 'It has no "result_type" and no "verdict". Open the result.json written by `slicepoint assess`.',
    );
  }
  const version = input.schema_version;
  const notes: string[] = [];
  if (version === undefined) {
    notes.push(`schema_version is not recorded; read as ${SCHEMA_VERSION}, the contract's default.`);
  } else if (version !== SCHEMA_VERSION) {
    return fail(
      `Unsupported schema version ${JSON.stringify(version)}`,
      `This viewer reads SlicePoint results with schema_version "${SCHEMA_VERSION}". ` +
        "The file was written against another version of the contract, so it is not shown rather than misread. " +
        "Use a viewer built for that version, or regenerate the result with a matching slicepoint-core.",
    );
  }
  const data = input;
  if (!validate(data)) {
    return fail(
      "This result does not match the SlicePoint contract",
      `The file says schema_version "${SCHEMA_VERSION}" but does not validate against the AssessmentResult ` +
        "schema. It may be damaged or edited by hand. Nothing from it is shown.",
      describeSchemaErrors(validate.errors ?? []),
    );
  }
  return { ok: true, result: data, compatNotes: notes };
}

/** Parse and validate the text of a result file. */
export function loadResultText(text: string): LoadOutcome {
  if (!text.trim()) return fail("The file is empty", "Choose the result.json written by `slicepoint assess`.");
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    return fail(
      "This file is not valid JSON",
      "A SlicePoint result is a JSON file (result.json). This file could not be read as JSON.",
      [e instanceof Error ? e.message : String(e)],
    );
  }
  return loadResultData(parsed);
}
