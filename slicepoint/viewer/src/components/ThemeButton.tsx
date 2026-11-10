// Light / dark / system toggle, shared by the static and live shells.
import { useEffect, useState } from "react";
import { applyTheme, readThemeChoice, saveThemeChoice, type ThemeChoice } from "../theme";
import { Button } from "./ui";

const THEME_NEXT: Record<ThemeChoice, ThemeChoice> = { system: "light", light: "dark", dark: "system" };
const THEME_LABEL: Record<ThemeChoice, string> = { system: "Theme: system", light: "Theme: light", dark: "Theme: dark" };

export function ThemeButton() {
  const [theme, setTheme] = useState<ThemeChoice>(readThemeChoice);

  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system" || typeof window.matchMedia !== "function") return;
    const mq = window.matchMedia("(prefers-color-scheme: dark)");
    const on = () => applyTheme("system");
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, [theme]);

  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={() => {
        const next = THEME_NEXT[theme];
        setTheme(next);
        saveThemeChoice(next);
      }}
      aria-label={`${THEME_LABEL[theme]}. Switch to ${THEME_NEXT[theme]}.`}
    >
      {THEME_LABEL[theme]}
    </Button>
  );
}
