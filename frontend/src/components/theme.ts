// The colour theme (D40: chosen in Settings): system, light or dark, kept in this browser only.
export type Theme = "system" | "light" | "dark";

const THEME_KEY = "flowforge.theme";

export function readTheme(): Theme {
  try {
    const t = localStorage.getItem(THEME_KEY);
    return t === "light" || t === "dark" ? t : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme: Theme): void {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", theme);
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* private window: the choice just isn't remembered */
  }
}
