// Appearance: "system" (follow the OS), "light" or "dark". A per-device preference kept in localStorage.

const THEME_KEY = "flowsense.theme";
const THEMES = ["system", "light", "dark"];

export function getTheme() {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    return THEMES.includes(saved) ? saved : "system";
  } catch {
    return "system";
  }
}

export function applyTheme(theme = getTheme()) {
  if (theme === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
}

export function setTheme(theme) {
  try {
    localStorage.setItem(THEME_KEY, theme);
  } catch {
    /* still applied for this visit */
  }
  applyTheme(theme);
  window.dispatchEvent(new CustomEvent("flowsense:theme", { detail: theme }));
}
