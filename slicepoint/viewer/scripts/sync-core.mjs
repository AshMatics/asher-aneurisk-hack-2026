// Copy the built single-file viewer into slicepoint-core, so `slicepoint assess --viewer`
// can write it next to result.json without the hospital downloading anything.
//
// Writes, under core/src/slicepoint_core/_viewer/:
//   slicepoint-viewer.html  the file from dist/ (run `pnpm build` first)
//   viewer.json             what it was built from: viewer version, the contract it reads
//                           (schema_version and the sha256 of AssessmentResult.schema.json)
//                           and the html's own sha256
//
// slicepoint-core's tests compare viewer.json with the current schema file, so a contract
// change without `pnpm build:core` fails CI instead of shipping a stale viewer.
import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const viewer = resolve(here, "..");
const src = join(viewer, "dist", "slicepoint-viewer.html");
const schema = resolve(viewer, "..", "schemas", "jsonschema", "AssessmentResult.schema.json");
const outDir = resolve(viewer, "..", "core", "src", "slicepoint_core", "_viewer");

const sha256 = (buf) => createHash("sha256").update(buf).digest("hex");

let html;
try {
  html = readFileSync(src);
} catch {
  console.error(`sync-core: ${src} not found; run \`pnpm build\` first`);
  process.exit(1);
}
const schemaBytes = readFileSync(schema);
const pkg = JSON.parse(readFileSync(join(viewer, "package.json"), "utf8"));
const meta = {
  viewer_version: pkg.version,
  schema_version: JSON.parse(schemaBytes.toString("utf8")).properties.schema_version.const,
  schema_sha256: sha256(schemaBytes),
  html_sha256: sha256(html),
};
if (!meta.schema_version) {
  console.error("sync-core: could not read schema_version from AssessmentResult.schema.json");
  process.exit(1);
}

mkdirSync(outDir, { recursive: true });
writeFileSync(join(outDir, "slicepoint-viewer.html"), html);
writeFileSync(join(outDir, "viewer.json"), JSON.stringify(meta, null, 2) + "\n");
console.log(`sync-core: copied viewer ${meta.viewer_version} (${Math.round(html.length / 1024)} kB) to ${outDir}`);
