// Entry point: decides between the login screen and the app shell, and routes between pages.

import { api, getToken, onUnauthorized, setToken } from "./api.js";
import { h, icon, mount, toast } from "./dom.js";
import { syncAgentToken } from "./desktop.js";
import { connectLive } from "./live.js";
import { renderLogin } from "./pages/login.js";
import { renderOnboarding } from "./pages/onboarding.js";
import { applyTheme } from "./theme.js";
import { renderDashboard } from "./pages/dashboard.js";
import { renderHome } from "./pages/home.js";
import { renderInsights } from "./pages/insights.js";
import { renderSettings } from "./pages/settings.js";
import { renderReports } from "./pages/reports.js";
import { store } from "./store.js";

const ROUTES = {
  home: { label: "Focus", icon: "home", render: renderHome },
  dashboard: { label: "Dashboard", icon: "chart", render: renderDashboard },
  insights: { label: "Insights", icon: "bulb", render: renderInsights },
  reports: { label: "Reports", icon: "file", render: renderReports },
  settings: { label: "Settings", icon: "gear", render: renderSettings },
};
const DEFAULT_ROUTE = "home";

const root = document.getElementById("app");
let live = null;
let cleanupPage = null;
let shell = null;

const TOKEN_REFRESH_MS = 6 * 60 * 60 * 1000;
let refreshTimer = null;

applyTheme(); // as early as possible, to avoid a flash of the wrong theme

// ---------- Session lifecycle ----------

async function boot() {
  onUnauthorized(() => logout("Your session expired. Please sign in again."));
  if (!getToken()) {
    showLogin();
    return;
  }
  try {
    store.setUser(await api.get("/auth/me"));
  } catch (error) {
    if (error.status === 401) return; // handler already showed the login screen
    showConnectionError(error.message);
    return;
  }
  enterApp();
}

/** After sign-in: first-run setup for new accounts, the app for everyone else. */
function enterApp() {
  if (store.user.onboarded) {
    showApp();
    return;
  }
  teardownApp();
  renderOnboarding(root, {
    onDone: (user) => {
      store.setUser(user);
      showApp();
    },
  });
}

/** Swap the token for a fresh one while the app is in use, so an active user is never signed out. */
async function refreshToken() {
  try {
    const { access_token: token } = await api.post("/auth/refresh");
    setToken(token);
    syncAgentToken(token);
  } catch {
    /* offline or expired: the 401 handler takes care of an expired token */
  }
}

function showConnectionError(message) {
  mount(
    root,
    h(
      "div",
      { class: "auth" },
      h(
        "div",
        { class: "card auth-card stack" },
        h("h2", {}, "Can't connect"),
        h("p", { class: "muted" }, message),
        h("button", { class: "btn btn-primary", onclick: boot }, "Try again"),
      ),
    ),
  );
}

function showLogin(message) {
  teardownApp();
  renderLogin(root, {
    message,
    onAuthenticated: (token, user) => {
      setToken(token);
      store.setUser(user);
      enterApp();
    },
  });
}

function logout(message) {
  setToken(null);
  syncAgentToken(null);
  store.setUser(null);
  store.setOpenSession(null);
  showLogin(message);
}

function teardownApp() {
  live?.close();
  live = null;
  cleanupPage?.();
  cleanupPage = null;
  shell?.dispose();
  shell = null;
  clearInterval(refreshTimer);
  window.removeEventListener("hashchange", renderRoute);
}

function showApp() {
  teardownApp();
  shell = buildShell();
  mount(root, shell.element);

  live = connectLive({
    onStatus: (status) => store.setLiveStatus(status),
    onUnauthorized: () => logout("Your session expired. Please sign in again."),
    onMessage: handleLiveMessage,
  });

  window.addEventListener("hashchange", renderRoute);
  renderRoute();
  syncAgentToken(getToken()); // lets the desktop agent track the screen for this user
  refreshToken();
  refreshTimer = setInterval(refreshToken, TOKEN_REFRESH_MS);
}

function handleLiveMessage(message) {
  switch (message.type) {
    case "snapshot":
      store.setOpenSession(message.session);
      store.emit("sessions-changed");
      break;
    case "session.updated":
      store.applySession(message.session);
      break;
    case "session.deleted":
      if (store.session?.id === message.session_id) store.setOpenSession(null);
      store.emit("sessions-changed");
      break;
    case "distraction.logged":
      store.emit("distraction-logged", message.distraction);
      break;
    case "distraction.updated":
      store.emit("distraction-updated", message.distraction);
      break;
    case "distraction.dismissed":
      store.emit("distraction-dismissed", message.distraction_id);
      break;
    case "activity.updated":
      store.emit("activity", message.activity);
      break;
    case "report.created": {
      const report = message.report;
      toast(`Your ${report.report_type} report is ready: ${report.data?.title ?? report.period_start}`, "success", 8000, {
        label: "View",
        onClick: () => (location.hash = `#/reports/${report.id}`),
      });
      store.emit("report-created", report);
      break;
    }
    default:
      break;
  }
}

// ---------- Shell & routing ----------

/** "#/reports/42" -> { name: "reports", param: "42" } */
function currentRoute() {
  const [name, param = null] = location.hash.replace(/^#\/?/, "").split("/");
  return ROUTES[name] ? { name, param } : { name: DEFAULT_ROUTE, param: null };
}

function buildShell() {
  const navLinks = Object.entries(ROUTES).map(([name, route]) =>
    h("a", { href: `#/${name}`, dataset: { route: name } }, icon(route.icon), h("span", {}, route.label)),
  );

  const liveStatus = h(
    "div",
    { class: "live-status", dataset: { status: store.liveStatus } },
    h("span", { class: "dot" }),
    h("span", { class: "label" }),
  );
  const updateStatus = (status) => {
    liveStatus.dataset.status = status;
    liveStatus.querySelector(".label").textContent = { online: "Live", offline: "Reconnecting…", connecting: "Connecting…" }[status];
  };
  updateStatus(store.liveStatus);
  const unsubscribe = store.on("live-status", updateStatus);

  const main = h("main", { class: "main", id: "main" });
  const element = h(
    "div",
    { class: "shell" },
    h(
      "aside",
      { class: "sidebar" },
      h("div", { class: "brand" }, h("img", { src: "assets/icon.svg", alt: "" }), "FlowSense"),
      h("nav", { class: "nav", "aria-label": "Main" }, navLinks),
      h(
        "div",
        { class: "sidebar-footer" },
        liveStatus,
        h("div", { class: "user-email", title: store.user.email }, store.user.email),
        h("button", { class: "btn btn-ghost btn-sm", onclick: () => logout() }, icon("logout"), "Sign out"),
      ),
    ),
    main,
  );
  return { element, main, navLinks, dispose: unsubscribe };
}

function renderRoute() {
  if (!shell) return;
  const { name, param } = currentRoute();
  for (const link of shell.navLinks) {
    if (link.dataset.route === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  cleanupPage?.();
  shell.main.replaceChildren();
  cleanupPage = ROUTES[name].render(shell.main, { logout, param }) ?? null;
  document.title = `${ROUTES[name].label} · FlowSense`;
  shell.main.focus?.();
}

window.addEventListener("unhandledrejection", (event) => {
  console.error(event.reason);
  toast(event.reason?.message ?? "Something went wrong", "error");
});

boot();
