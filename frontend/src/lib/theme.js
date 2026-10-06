import { useCallback, useEffect, useState } from "react";

const KEY = "plumbline_theme";

function stored() {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

export function systemTheme() {
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

/** Light/dark theme: follows the OS until the user picks one, then remembers it. */
export function useTheme() {
  const [theme, setTheme] = useState(() => stored() || systemTheme());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === "dark" ? "light" : "dark";
      try { localStorage.setItem(KEY, next); } catch { /* private mode */ }
      return next;
    });
  }, []);

  return { theme, toggle };
}

/** Current theme for non-CSS consumers (three.js). */
export function currentTheme() {
  return document.documentElement.dataset.theme === "dark" ? "dark" : "light";
}
