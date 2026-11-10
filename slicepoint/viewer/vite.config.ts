import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";
import { viteSingleFile } from "vite-plugin-singlefile";

// One self-contained HTML file: every script, style and sample is inlined, so the viewer
// opens from file:// with no server and makes no network request. scripts/check-build.mjs
// then adds the Content-Security-Policy (hashes of the inline script and style), verifies
// that nothing external is referenced and writes dist/slicepoint-viewer.html.
export default defineConfig({
  base: "./",
  plugins: [react(), tailwindcss(), viteSingleFile({ removeViteModuleLoader: true })],
  build: {
    target: "es2022",
    assetsInlineLimit: Number.MAX_SAFE_INTEGER,
    cssCodeSplit: false,
    reportCompressedSize: true,
    modulePreload: false,
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
