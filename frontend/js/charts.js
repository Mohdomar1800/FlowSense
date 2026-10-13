// Chart.js (vendored in /vendor, MIT) is loaded on first use, so other pages never pay for it.

let loading = null;

export function loadChartJs() {
  if (window.Chart) return Promise.resolve(window.Chart);
  loading ??= new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "vendor/chart.umd.min.js";
    script.onload = () => resolve(window.Chart);
    script.onerror = () => {
      loading = null;
      reject(new Error("Couldn't load the charting library"));
    };
    document.head.append(script);
  });
  return loading;
}

/** Current theme colors, read from the CSS tokens so charts follow light/dark mode. */
export function themeColors() {
  const css = getComputedStyle(document.documentElement);
  const token = (name) => css.getPropertyValue(name).trim();
  return {
    accent: token("--accent"),
    success: token("--success"),
    warning: token("--warning"),
    danger: token("--danger"),
    text: token("--text"),
    muted: token("--text-muted"),
    border: token("--border"),
    surface: token("--surface"),
  };
}

/** Calls `handler` when the theme changes (OS light/dark switch or the Settings choice); returns an unsubscribe. */
export function onThemeChange(handler) {
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  query.addEventListener("change", handler);
  window.addEventListener("flowsense:theme", handler);
  return () => {
    query.removeEventListener("change", handler);
    window.removeEventListener("flowsense:theme", handler);
  };
}
