#!/usr/bin/env node
// Copy the live viewer build (dist-live/) into slicepoint-api, so `pip install
// slicepoint-api` serves the web UI at / without Node or pnpm.
//
// Replaces api/src/slicepoint_api/_ui/ with:
//   index.html, assets/*   the files from dist-live/ (run `pnpm build:live` first)
//   ui.json                what it was built from: viewer version, the sha256 of the
//                          api/openapi.json and AssessmentResult.schema.json it was
//                          generated against, and the sha256 of every copied file
//
// slicepoint-api's tests compare ui.json with the current openapi.json and schema, and
// with the copied files, so an API or contract change without `pnpm build:api` fails the
// tests instead of shipping a stale UI. Mirrors sync-core.mjs.
import { createHash } from "node:crypto";
import { cpSync, existsSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const viewer = resolve(here, "..");
const src = join(viewer, "dist-live");
const openapi = resolve(viewer, "..", "api", "openapi.json");
const schema = resolve(viewer, "..", "schemas", "jsonschema", "AssessmentResult.schema.json");
const outDir = resolve(viewer, "..", "api", "src", "slicepoint_api", "_ui");

const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");

if (!existsSync(join(src, "index.html"))) {
  console.error(`sync-api: ${src}/index.html not found; run \`pnpm build:live\` first`);
  process.exit(1);
}

rmSync(outDir, { recursive: true, force: true });
cpSync(src, outDir, { recursive: true });

const files = {};
for (const f of readdirSync(outDir, { recursive: true }).map(String).sort()) {
  const p = join(outDir, f);
  if (statSync(p).isFile()) files[f.split("\\").join("/")] = sha256(readFileSync(p));
}
const pkg = JSON.parse(readFileSync(join(viewer, "package.json"), "utf8"));
const meta = {
  viewer_version: pkg.version,
  openapi_sha256: sha256(readFileSync(openapi)),
  schema_sha256: sha256(readFileSync(schema)),
  files,
};
writeFileSync(join(outDir, "ui.json"), JSON.stringify(meta, null, 2) + "\n");
console.log(`sync-api: copied live viewer ${meta.viewer_version} (${Object.keys(files).length} files) to ${outDir}`);
