import js from "@eslint/js";
import reactHooks from "eslint-plugin-react-hooks";
import globals from "globals";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "node_modules", "src/contract/*.generated.*", "coverage"] },
  {
    files: ["**/*.{ts,tsx}"],
    extends: [js.configs.recommended, ...tseslint.configs.strict],
    languageOptions: { ecmaVersion: 2022, globals: { ...globals.browser } },
    plugins: { "react-hooks": reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: "The viewer makes no network requests." },
        { name: "XMLHttpRequest", message: "The viewer makes no network requests." },
        { name: "WebSocket", message: "The viewer makes no network requests." },
        { name: "EventSource", message: "The viewer makes no network requests." },
      ],
    },
  },
  {
    // View-models are plain TypeScript so a Vue shell can reuse them (ADR 0001 §7).
    files: ["src/viewmodel/**/*.ts"],
    rules: {
      "no-restricted-imports": ["error", { patterns: ["react", "react-dom", "react/*", "react-dom/*", "../components/*"] }],
    },
  },
  {
    files: ["scripts/**/*.mjs"],
    extends: [js.configs.recommended],
    languageOptions: { globals: { ...globals.node } },
  },
);
