import { useSyncExternalStore } from "react";

/* Light or dark. The system preference decides until the reader picks one; the pick is remembered.
   index.html applies a stored pick before first paint, so there is no flash of the wrong ground.
   Canvas and WebGL code cannot read CSS, so `token()` hands it the live values and `useTheme()`
   tells it when to redraw. */

export type Theme = "light" | "dark";
const KEY = "receipts.theme";
const media = typeof matchMedia === "function" ? matchMedia("(prefers-color-scheme: dark)") : null;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
media?.addEventListener?.("change", emit);

function stored(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === "light" || v === "dark" ? v : null;
  } catch {
    return null;
  }
}

export const currentTheme = (): Theme => stored() ?? (media?.matches ? "dark" : "light");

export function setTheme(t: Theme): void {
  try { localStorage.setItem(KEY, t); } catch { /* private mode: it just won't be remembered */ }
  document.documentElement.dataset.theme = t;
  emit();
}

export function useTheme(): Theme {
  return useSyncExternalStore(
    (cb) => { listeners.add(cb); return () => { listeners.delete(cb); }; },
    currentTheme,
    () => "light",
  );
}

/** A design token's current value, e.g. token("--ink"). */
export const token = (name: string): string =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();
