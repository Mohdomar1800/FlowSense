// Small DOM and formatting helpers.
// Elements are always built with h(); text is set with textContent, never innerHTML,
// so user-entered values (tag names, intents) can never inject markup.

/**
 * Create an element: h("button", { class: "btn", onclick: fn }, "Label", childEl)
 * - keys starting with "on" become event listeners
 * - `class`, `dataset`, `style`, boolean and other attributes are supported
 * - children may be strings, numbers, elements, arrays, or null/false (skipped)
 */
export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "class") {
      el.className = value;
    } else if (key === "dataset") {
      Object.assign(el.dataset, value);
    } else if (key === "style" && typeof value === "object") {
      Object.assign(el.style, value);
    } else if (key === "value") {
      el.value = value;
    } else if (key === "checked") {
      el.checked = Boolean(value);
    } else {
      el.setAttribute(key, value === true ? "" : String(value));
    }
  }
  append(el, children);
  return el;
}

function append(parent, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    parent.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

/** Replace all children of `el`. */
export function mount(el, ...children) {
  el.replaceChildren();
  append(el, children);
}

// ---------- Icons (inline SVG, stroke style) ----------

const ICON_PATHS = {
  play: ["M8 5.5v13l11-6.5z"],
  pause: ["M8 5h3v14H8z", "M13 5h3v14h-3z"],
  stop: ["M6.5 6.5h11v11h-11z"],
  home: ["M3 10.5 12 3l9 7.5", "M5.5 9v11h13V9"],
  chart: ["M4 20V10", "M10 20V4", "M16 20v-7", "M22 20H2"],
  bulb: ["M9 18h6", "M10 21h4", "M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z"],
  file: ["M14 3H6v18h12V7z", "M14 3v4h4", "M9 12h6", "M9 16h6"],
  gear: [
    "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z",
    "M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z",
  ],
  bell: ["M6 8a6 6 0 1 1 12 0c0 7 3 9 3 9H3s3-2 3-9", "M10.3 21a1.9 1.9 0 0 0 3.4 0"],
  logout: ["M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4", "M16 17l5-5-5-5", "M21 12H9"],
  trash: ["M3 6h18", "M8 6V4h8v2", "M6 6l1 15h10l1-15"],
  plus: ["M12 5v14", "M5 12h14"],
};

const FILLED_ICONS = new Set(["play", "pause", "stop"]);

export function icon(name, extraClass = "") {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("class", `icon ${extraClass}`.trim());
  svg.setAttribute("aria-hidden", "true");
  const filled = FILLED_ICONS.has(name);
  svg.setAttribute("fill", filled ? "currentColor" : "none");
  svg.setAttribute("stroke", filled ? "none" : "currentColor");
  svg.setAttribute("stroke-width", "1.8");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  for (const d of ICON_PATHS[name] ?? []) {
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    svg.append(path);
  }
  return svg;
}

// ---------- Formatting ----------

const pad = (n) => String(n).padStart(2, "0");

/** 3725 -> "1:02:05", 125 -> "02:05" */
export function formatClock(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  const seconds = s % 60;
  return hours ? `${hours}:${pad(minutes)}:${pad(seconds)}` : `${pad(minutes)}:${pad(seconds)}`;
}

/** 3725 -> "1h 02m", 1500 -> "25m", 40 -> "40s" */
export function formatDuration(totalSeconds) {
  const s = Math.max(0, Math.floor(totalSeconds));
  if (s < 60) return `${s}s`;
  const hours = Math.floor(s / 3600);
  const minutes = Math.floor((s % 3600) / 60);
  return hours ? `${hours}h ${pad(minutes)}m` : `${minutes}m`;
}

// Times and "today" follow the account's timezone (Settings), not the computer's, so they always match
// the server's day boundaries. Undefined means the browser's own zone (before sign-in).
let displayTimeZone;

export function setDisplayTimeZone(timeZone) {
  try {
    new Intl.DateTimeFormat([], { timeZone }); // throws on an unknown zone
    displayTimeZone = timeZone;
  } catch {
    displayTimeZone = undefined;
  }
}

export function formatTime(iso) {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", timeZone: displayTimeZone });
}

export function formatLongDate(date = new Date()) {
  return date.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric", timeZone: displayTimeZone });
}

/** Today's date (YYYY-MM-DD) in the account's timezone. */
export function todayIso() {
  return new Intl.DateTimeFormat("en-CA", { timeZone: displayTimeZone }).format(new Date());
}

/** The current hour (0-23) in the account's timezone. */
export function currentHour() {
  const hour = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", hourCycle: "h23", timeZone: displayTimeZone }).format(new Date());
  return Number(hour);
}

export function scoreLevel(score) {
  if (score >= 80) return "high";
  if (score >= 50) return "mid";
  return "low";
}

// ---------- Toasts ----------

/** Show a short message. `action` ({ label, onClick }) adds a button, e.g. "View" on "Report ready". */
export function toast(message, kind = "info", timeoutMs = 3500, action = null) {
  const container = document.getElementById("toasts");
  const el = h(
    "div",
    { class: "toast", dataset: { kind } },
    h("span", {}, message),
    action &&
      h(
        "button",
        {
          class: "link-button toast-action",
          onclick: () => {
            el.remove();
            action.onClick();
          },
        },
        action.label,
      ),
  );
  container.append(el);
  setTimeout(() => el.remove(), timeoutMs);
}
