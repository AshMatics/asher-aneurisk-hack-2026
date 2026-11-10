import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vitest/config";
import { viteSingleFile } from "vite-plugin-singlefile";

// Two builds from one codebase, chosen by Vite's mode.
//
// Static (default, `pnpm build`): index.html -> src/main.tsx. One self-contained HTML file:
// every script, style and sample is inlined, so the viewer opens from file:// with no
// server and makes no network request. scripts/check-build.mjs then adds the
// Content-Security-Policy (hashes of the inline script and style), verifies that nothing
// external is referenced and that no live-mode code is in the bundle, and writes
// dist/slicepoint-viewer.html. The static entry never imports src/live, so the API client
// is not compiled into it at all.
//
// Live (`--mode live`, `pnpm build:live` / `pnpm dev:live`): live.html -> src/live/main.tsx,
// built to dist-live/ for slicepoint-api to serve at / (SLICEPOINT_UI_DIR). Ordinary
// files under /assets/, loaded same-origin; scripts/check-live.mjs renames live.html to
// index.html and checks there is no inline script or style and nothing external. In dev,
// Vite proxies /v1 to the API on 127.0.0.1:8100 and serves live.html at /.
const API = process.env.SLICEPOINT_API_URL ?? "http://127.0.0.1:8100";

function liveIndex(): Plugin {
  return {
    name: "slicepoint-live-index",
    configureServer(server) {
      server.middlewares.use((req, _res, next) => {
        if (req.url === "/" || req.url?.startsWith("/?")) req.url = "/live.html" + req.url.slice(1);
        next();
      });
    },
  };
}

export default defineConfig(({ mode }) => {
  const live = mode === "live";
  return {
    base: live ? "/" : "./",
    plugins: [
      react(),
      tailwindcss(),
      ...(live ? [liveIndex()] : [viteSingleFile({ removeViteModuleLoader: true })]),
    ],
    build: live
      ? {
          target: "es2022",
          outDir: "dist-live",
          emptyOutDir: true,
          assetsInlineLimit: 0,
          cssCodeSplit: false,
          modulePreload: false,
          rollupOptions: { input: "live.html" },
          chunkSizeWarningLimit: 1024,
        }
      : {
          target: "es2022",
          assetsInlineLimit: Number.MAX_SAFE_INTEGER,
          cssCodeSplit: false,
          reportCompressedSize: true,
          modulePreload: false,
        },
    server: live
      ? { proxy: { "/v1": { target: API, changeOrigin: false }, "/healthz": { target: API } } }
      : {},
    test: {
      environment: "jsdom",
      globals: true,
      setupFiles: ["./src/test/setup.ts"],
      include: ["src/**/*.test.{ts,tsx}"],
    },
  };
});
