#!/usr/bin/env node
// Post-build: make dist/index.html a strict, offline, single file and copy it to
// dist/slicepoint-viewer.html.
//
// 1. Checks the build is one HTML file: one inline <script>, inline <style>s, and no
//    src/href to anything (no external script, stylesheet, font, image or preload).
// 2. Adds a Content-Security-Policy meta: default-src 'none', and the inline script and
//    styles allowed by their sha256 hashes only (no 'unsafe-inline', no 'unsafe-eval').
//    connect-src is not listed, so it falls back to 'none': fetch/XHR/WebSocket are blocked.
// 3. Fails on anything that would make a request: http(s) URLs in src/href/url()/@import,
//    or network APIs (fetch, XMLHttpRequest, WebSocket, EventSource, sendBeacon) in the code.
//    Plain http(s) strings that are never requested (XML namespaces, React's error-page
//    link) are listed for the record.
// 4. Fails if any live-mode code (src/live: the slicepoint-api client) was compiled in.
//    The static entry never imports it; this proves it on the built bytes.
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { gzipSync } from "node:zlib";

const dist = resolve(dirname(fileURLToPath(import.meta.url)), "../dist");
const indexPath = resolve(dist, "index.html");
let html = readFileSync(indexPath, "utf8");
const problems = [];

const files = readdirSync(dist, { recursive: true }).filter((f) => !String(f).startsWith("."));
const extra = files.filter((f) => !["index.html", "slicepoint-viewer.html"].includes(String(f)));
if (extra.length) problems.push(`dist has files besides index.html: ${extra.join(", ")}`);

const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
const styles = [...html.matchAll(/<style\b([^>]*)>([\s\S]*?)<\/style>/g)];
if (scripts.length !== 1) problems.push(`expected exactly one inline <script>, found ${scripts.length}`);
for (const [, attrs] of scripts) if (/\bsrc\s*=/.test(attrs)) problems.push("a <script> has a src attribute");
if (/<link\b/i.test(html)) problems.push("the page has a <link> element (stylesheet, preload or icon)");
if (/\s(?:src|href|srcset|poster|action|formaction)\s*=\s*["']?(?!#|data:)[^"'\s>]/i.test(html.replace(/<script\b[\s\S]*?<\/script>|<style\b[\s\S]*?<\/style>/g, ""))) {
  problems.push("the page markup references an external resource (src/href)");
}

const code = scripts.map((m) => m[2]).join("\n");
const css = styles.map((m) => m[2]).join("\n");
if (/@import\s/.test(css)) problems.push("CSS uses @import");
if (/url\(\s*["']?(?:https?:)?\/\//.test(css)) problems.push("CSS loads a remote url()");
const network = ["fetch(", "XMLHttpRequest", "new WebSocket", "EventSource", "sendBeacon", "importScripts"];
for (const api of network) {
  // `fetch(` also matches identifiers such as `prefetch(`; require a non-identifier before it.
  const re = new RegExp(`(^|[^\\w$.])${api.replace(/[()]/g, "\\$&")}`);
  if (re.test(code)) problems.push(`the script uses a network API: ${api}`);
}
// Markers of the live build's API client (src/live/client.ts). None may reach the static file.
const liveMarkers = [
  [/\/v1\//, "an API path (/v1/)"],
  [/x-slicepoint-csrf/i, "the CSRF header name"],
  [/credentials\s*:\s*["']same-origin/, "a fetch credentials option"],
  [/\bfetchImpl\b|\bcreateClient\b|\bonUnauthorized\b/, "the live API client"],
];
for (const [re, what] of liveMarkers) if (re.test(code)) problems.push(`live-mode code in the static bundle: ${what}`);
const urls = [...new Set([...code.matchAll(/https?:\/\/[^"'`\s)\\]+/g)].map((m) => m[0]))].sort();

const sha = (s) => `'sha256-${createHash("sha256").update(s, "utf8").digest("base64")}'`;
const csp = [
  "default-src 'none'",
  `script-src ${scripts.map((m) => sha(m[2])).join(" ")}`,
  `style-src ${styles.map((m) => sha(m[2])).join(" ")}`,
  "img-src data:",
  "base-uri 'none'",
  "form-action 'none'",
].join("; ");

html = html.replace(/<meta http-equiv="Content-Security-Policy"[^>]*>\s*/i, "");
html = html.replace(/<meta charset="utf-8"\s*\/?>/i, (m) => `${m}\n    <meta http-equiv="Content-Security-Policy" content="${csp}" />`);
if (!html.includes("Content-Security-Policy")) problems.push("could not insert the CSP meta (no <meta charset>)");

if (problems.length) {
  console.error("check-build: the single-file viewer is not self-contained:\n- " + problems.join("\n- "));
  process.exit(1);
}
writeFileSync(indexPath, html);
writeFileSync(resolve(dist, "slicepoint-viewer.html"), html);
const kb = (n) => `${(n / 1024).toFixed(0)} kB`;
console.log(`check-build: dist/slicepoint-viewer.html ${kb(Buffer.byteLength(html))} (gzip ${kb(gzipSync(html).length)}), one inline script, ${styles.length} inline style(s).`);
console.log(`check-build: CSP ${csp.replace(/'sha256-[^']+'/g, "'sha256-…'")}`);
console.log(`check-build: no external references, no network APIs and no live-mode code. URL strings in the code (never requested): ${urls.length ? urls.join(", ") : "none"}`);
