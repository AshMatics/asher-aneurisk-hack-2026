// Entry point of the live build only (live.html, `pnpm build:live`). The static build's
// entry (src/main.tsx) never imports anything under src/live.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "../index.css";
import { applyTheme, readThemeChoice } from "../theme";
import { LiveApp } from "./LiveApp";

applyTheme(readThemeChoice());

const root = document.getElementById("root");
if (!root) throw new Error("missing #root");
createRoot(root).render(
  <StrictMode>
    <LiveApp />
  </StrictMode>,
);
