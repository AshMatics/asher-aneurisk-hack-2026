#!/usr/bin/env node
// Post-build for the live viewer (dist-live/, served by slicepoint-api at / when
// SLICEPOINT_UI_DIR points here).
//
// 1. Renames live.html to index.html (the API serves / and /index.html).
// 2. Checks the page works under the API's live CSP (slicepoint_api/ui.py):
//    default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; ...
//    so: no inline <script> or <style>, no inline event handlers, every script and
//    stylesheet is a same-origin file under /assets/ that exists, and nothing external
//    (no http(s) src/href, CSS @import or remote url()).
// 3. Checks the code talks to the API only through fetch with the session cookie: no
//    XHR, WebSocket, EventSource or sendBeacon, no Authorization/Bearer header, and no
//    sessionStorage (the token is never stored; localStorage holds only the theme).
// 4. Checks every file has a type the API will serve.
import { existsSync, readFileSync, readdirSync, renameSync, statSync } from "node:fs";
import { dirname, extname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const dist = resolve(dirname(fileURLToPath(import.meta.url)), "../dist-live");
const problems = [];
if (existsSync(resolve(dist, "live.html"))) renameSync(resolve(dist, "live.html"), resolve(dist, "index.html"));
const html = readFileSync(resolve(dist, "index.html"), "utf8");

const scripts = [...html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)];
if (!scripts.length) problems.push("index.html has no <script>");
for (const [, attrs, body] of scripts) {
  if (body.trim()) problems.push("index.html has an inline <script> (blocked by script-src 'self')");
  const src = /\bsrc="([^"]+)"/.exec(attrs)?.[1];
  if (!src?.startsWith("/assets/")) problems.push(`a <script> is not a same-origin /assets/ file: ${src ?? "(none)"}`);
}
if (/<style\b/i.test(html)) problems.push("index.html has an inline <style> (blocked by style-src 'self')");
if (/\sstyle\s*=/i.test(html)) problems.push("index.html has a style attribute");
if (/\son[a-z]+\s*=/i.test(html)) problems.push("index.html has an inline event handler");
const refs = [...html.matchAll(/\s(?:src|href)\s*=\s*"([^"]*)"/g)].map((m) => m[1]);
for (const ref of refs) {
  if (!ref.startsWith("/assets/")) problems.push(`index.html references something outside /assets/: ${ref}`);
  else if (!existsSync(resolve(dist, "." + ref))) problems.push(`index.html references a missing file: ${ref}`);
}

const SERVED = new Set([".html", ".js", ".css", ".svg", ".png", ".ico", ".json", ".map", ".woff2", ".txt"]);
const files = readdirSync(dist, { recursive: true }).map(String).filter((f) => statSync(resolve(dist, f)).isFile());
for (const f of files) {
  if (f.split(/[\\/]/).some((p) => p.startsWith("."))) problems.push(`dot-file in dist-live: ${f}`);
  if (!SERVED.has(extname(f).toLowerCase())) problems.push(`file type the API will not serve: ${f}`);
  if (f !== "index.html" && !f.startsWith("assets")) problems.push(`file outside assets/ (not served): ${f}`);
}
const code = files.filter((f) => f.endsWith(".js")).map((f) => readFileSync(resolve(dist, f), "utf8")).join("\n");
const css = files.filter((f) => f.endsWith(".css")).map((f) => readFileSync(resolve(dist, f), "utf8")).join("\n");
if (!code) problems.push("no JavaScript in dist-live/assets");
if (/@import\s/.test(css)) problems.push("CSS uses @import");
if (/url\(\s*["']?(?:https?:)?\/\//.test(css)) problems.push("CSS loads a remote url()");
const forbidden = [
  [/(^|[^\w$.])XMLHttpRequest/, "XMLHttpRequest"],
  [/new WebSocket/, "WebSocket"],
  [/EventSource/, "EventSource"],
  [/sendBeacon/, "sendBeacon"],
  [/importScripts/, "importScripts"],
  [/sessionStorage/, "sessionStorage"],
  [/["']Bearer\s/, "a Bearer authorization header"],
  [/["']Authorization["']/, "an Authorization header"],
];
for (const [re, what] of forbidden) if (re.test(code)) problems.push(`the live code uses ${what}`);
if (!/x-slicepoint-csrf/i.test(code)) problems.push("the live code does not send the CSRF header");

if (problems.length) {
  console.error("check-live: dist-live is not fit to serve under the live CSP:\n- " + problems.join("\n- "));
  process.exit(1);
}
const kb = (n) => `${(n / 1024).toFixed(0)} kB`;
const size = files.reduce((n, f) => n + statSync(resolve(dist, f)).size, 0);
console.log(`check-live: dist-live/index.html + ${files.length - 1} asset(s), ${kb(size)} in all; no inline script or style, nothing external.`);
console.log("check-live: serve it with SLICEPOINT_UI_DIR=" + dist);
