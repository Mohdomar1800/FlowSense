// Home: the big focus button, live timer, session controls, and today's progress.

import { api, query } from "../api.js";
import {
  currentHour,
  formatClock,
  formatDuration,
  formatLongDate,
  formatTime,
  h,
  icon,
  mount,
  scoreLevel,
  toast,
} from "../dom.js";
import { getCameraStatus } from "../desktop.js";
import { insightCard } from "./insights.js";
import { openSessionDialog } from "./session-dialog.js";
import { currentFocusSeconds, currentPauseSeconds, store } from "../store.js";

const LAST_TAG_KEY = "flowsense.lastTagId";

function greeting() {
  const hour = currentHour();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function readLastTag() {
  try {
    return localStorage.getItem(LAST_TAG_KEY) ?? "";
  } catch {
    return "";
  }
}

function saveLastTag(value) {
  try {
    localStorage.setItem(LAST_TAG_KEY, value);
  } catch {
    /* not important */
  }
}

export function renderHome(container) {
  const cleanups = [];
  let tags = [];
  let settings = null;
  let today = { sessions: [], distractions: 0 };
  let busy = false;

  // ---------- Focus card elements ----------

  const statusPill = h("span", { class: "focus-status" });
  const buttonInner = h("span", { class: "focus-button-inner" });
  const focusButton = h("button", { class: "focus-button", type: "button", onclick: onMainButton }, buttonInner);
  const intentInput = h("input", {
    class: "input",
    maxlength: 200,
    placeholder: "What are you working on?",
    "aria-label": "What are you working on?",
  });
  const tagSelect = h("select", { class: "input", "aria-label": "Tag" });
  const setup = h("div", { class: "focus-setup" }, intentInput, tagSelect);
  const intentLabel = h("p", { class: "focus-intent" });
  const pauseNote = h("p", { class: "pause-note muted" });
  const actions = h("div", { class: "focus-actions" });
  const activityLine = h("p", { class: "activity-line", hidden: true });
  const cameraBadge = h(
    "span",
    { class: "camera-badge", hidden: true, title: "Analyzed on this computer only. Nothing is recorded." },
    h("span", { class: "dot", "aria-hidden": "true" }),
    "Camera on",
  );
  const driftAlert = h("div", { class: "drift-alert", role: "alert", hidden: true });

  const focusCard = h(
    "section",
    { class: "card focus-card", "aria-label": "Focus session" },
    driftAlert,
    statusPill,
    focusButton,
    intentLabel,
    setup,
    pauseNote,
    actions,
    h("div", { class: "row", style: { flexWrap: "wrap", justifyContent: "center" } }, activityLine, cameraBadge),
  );

  // ---------- Today card elements ----------

  const goalText = h("span", { class: "small muted" });
  const progressFill = h("div", { style: { width: "0%" } });
  const progress = h("div", { class: "progress", role: "progressbar", "aria-label": "Daily goal" }, progressFill);
  const focusValue = h("div", { class: "metric-value" }, "0m");
  const sessionsValue = h("div", { class: "metric-value" }, "0");
  const distractionsValue = h("div", { class: "metric-value" }, "0");
  const sessionList = h("ul", { class: "session-list" });

  const tipSlot = h("div", {});
  const todayCard = h(
    "section",
    { class: "card stack", "aria-label": "Today" },
    h("div", { class: "card-header" }, h("h2", {}, "Today"), goalText),
    progress,
    h(
      "div",
      { class: "metric-row" },
      h("div", { class: "metric" }, focusValue, h("div", { class: "metric-label" }, "Focused")),
      h("div", { class: "metric" }, sessionsValue, h("div", { class: "metric-label" }, "Sessions")),
      h("div", { class: "metric" }, distractionsValue, h("div", { class: "metric-label" }, "Distractions")),
    ),
    h("h2", {}, "Sessions"),
    sessionList,
  );

  mount(
    container,
    h(
      "header",
      { class: "page-header" },
      h("div", {}, h("h1", {}, greeting()), h("p", { class: "muted" }, formatLongDate())),
    ),
    h("div", { class: "home-grid" }, focusCard, h("div", { class: "stack" }, todayCard, tipSlot)),
  );

  // ---------- Rendering ----------

  function tagById(id) {
    return tags.find((t) => t.id === id) ?? null;
  }

  function renderTagOptions() {
    const selected = tagSelect.value || readLastTag();
    mount(
      tagSelect,
      h("option", { value: "" }, "No tag"),
      tags.map((t) => h("option", { value: String(t.id) }, t.name)),
    );
    tagSelect.value = tags.some((t) => String(t.id) === selected) ? selected : "";
  }

  function renderFocus() {
    const session = store.session;
    const state = session?.status ?? "idle";
    focusButton.dataset.state = state;
    statusPill.dataset.state = state;
    focusButton.disabled = busy;

    if (state === "idle") {
      statusPill.textContent = "Ready";
      mount(
        buttonInner,
        icon("play"),
        h("span", { class: "focus-button-label" }, "Start focus"),
        h("span", { class: "focus-button-hint" }, "or press Space"),
      );
      focusButton.setAttribute("aria-label", "Start focus session");
      setup.hidden = false;
      intentLabel.hidden = true;
      pauseNote.hidden = true;
      mount(actions);
      return;
    }

    const tag = tagById(session.tag_id);
    setup.hidden = true;
    intentLabel.hidden = !session.intent && !tag;
    mount(
      intentLabel,
      session.intent ?? "",
      tag && h("span", { class: "chip", style: { marginLeft: "8px" } }, h("span", { class: "chip-dot", style: { background: tag.color } }), tag.name),
    );

    const timer = h("span", { class: "timer", "data-timer": "" }, formatClock(currentFocusSeconds()));
    if (state === "active") {
      statusPill.textContent = "Focusing";
      mount(buttonInner, timer, h("span", { class: "focus-button-hint" }, "Click to pause"));
      focusButton.setAttribute("aria-label", "Pause session");
      pauseNote.hidden = true;
    } else {
      statusPill.textContent = "Paused";
      mount(buttonInner, timer, h("span", { class: "focus-button-hint" }, "Click to resume"));
      focusButton.setAttribute("aria-label", "Resume session");
      pauseNote.hidden = false;
      updatePauseNote();
    }

    mount(
      actions,
      state === "active"
        ? h("button", { class: "btn", onclick: () => run(pause), disabled: busy }, icon("pause"), "Pause")
        : h("button", { class: "btn btn-primary", onclick: () => run(resume), disabled: busy }, icon("play"), "Resume"),
      h("button", { class: "btn", onclick: () => run(stop), disabled: busy }, icon("stop"), "Stop"),
      state === "active" &&
        h("button", { class: "btn btn-ghost", onclick: () => run(logDistraction), disabled: busy }, icon("bell"), "I got distracted"),
    );
  }

  function updatePauseNote() {
    const thresholdMin = Math.round((store.session?.pause_threshold_seconds ?? 300) / 60);
    pauseNote.textContent =
      `On a break for ${formatClock(currentPauseSeconds())}. ` +
      `Breaks longer than ${thresholdMin} min start a new session when you resume.`;
  }

  function todayFocusSeconds() {
    // Finished sessions from the server, plus the open session's live value.
    const openId = store.session?.id;
    const finished = today.sessions.filter((s) => s.id !== openId).reduce((sum, s) => sum + s.duration_seconds, 0);
    return finished + (store.session ? currentFocusSeconds() : 0);
  }

  function renderTodayNumbers() {
    const focused = todayFocusSeconds();
    focusValue.textContent = formatDuration(focused);
    const goalSeconds = (settings?.daily_focus_goal_minutes ?? 0) * 60;
    if (goalSeconds > 0) {
      const ratio = Math.min(1, focused / goalSeconds);
      progressFill.style.width = `${(ratio * 100).toFixed(1)}%`;
      progress.dataset.complete = String(ratio >= 1);
      progress.setAttribute("aria-valuenow", String(Math.round(ratio * 100)));
      goalText.textContent = ratio >= 1 ? "Daily goal reached" : `Goal ${formatDuration(goalSeconds)}`;
      progress.hidden = false;
    } else {
      progress.hidden = true;
      goalText.textContent = "";
    }
  }

  function renderToday() {
    const openSession = store.session;
    const sessions = today.sessions.some((s) => s.id === openSession?.id) || !openSession ? today.sessions : [openSession, ...today.sessions];
    sessionsValue.textContent = String(sessions.length);
    distractionsValue.textContent = String(today.distractions);
    renderTodayNumbers();

    if (sessions.length === 0) {
      mount(sessionList, h("li", { class: "empty" }, "No sessions yet today. Press Start when you're ready."));
      return;
    }
    mount(
      sessionList,
      sessions.map((s) => {
        const tag = tagById(s.tag_id);
        const open = s.status !== "ended";
        return h(
          "li",
          {
            class: "session-item clickable",
            role: "button",
            tabindex: 0,
            title: "Details, edit or delete",
            onclick: () => openSessionDialog(s.id, tags),
            onkeydown: (event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                openSessionDialog(s.id, tags);
              }
            },
          },
          h("span", { class: "title" }, s.intent || tag?.name || "Focus session"),
          open
            ? h("span", { class: "chip" }, s.status === "paused" ? "Paused" : "In progress")
            : h("span", { class: "score", dataset: { level: scoreLevel(s.focus_score) }, title: "Focus score" }, s.focus_score),
          h(
            "span",
            { class: "small muted" },
            open
              ? `Started ${formatTime(s.start_time)}`
              : `${formatTime(s.start_time)} – ${formatTime(s.end_time)} · ${formatDuration(s.duration_seconds)}`,
          ),
          h("span", { class: "small muted" }, s.distraction_count ? `${s.distraction_count} distraction${s.distraction_count > 1 ? "s" : ""}` : ""),
        );
      }),
    );
  }

  // ---------- Screen tracking: current activity and drift alerts ----------

  const CATEGORY_LABELS = { focus: "On task", neutral: "Neutral", distracting: "Off task" };
  let alertDistraction = null;

  function renderActivity(activity) {
    if (!activity || !store.session || store.session.status !== "active") {
      activityLine.hidden = true;
      return;
    }
    activityLine.hidden = false;
    activityLine.dataset.category = activity.category;
    activityLine.title = activity.reason;
    mount(
      activityLine,
      h("span", { class: "dot", "aria-hidden": "true" }),
      h("span", { class: "muted" }, "Now: "),
      h("strong", {}, activity.subject),
      h("span", { class: "muted" }, ` · ${CATEGORY_LABELS[activity.category] ?? activity.category}`),
    );
  }

  function showDriftAlert(distraction) {
    alertDistraction = distraction;
    const subject = distraction.subject ?? "something else";
    mount(
      driftAlert,
      h(
        "div",
        { class: "drift-alert-text" },
        h("strong", {}, distraction.event_type === "camera" ? "Phone down?" : `You drifted to ${subject}`),
        distraction.reason && h("span", { class: "small muted" }, distraction.reason),
      ),
      h(
        "div",
        { class: "row" },
        h("button", { class: "btn btn-sm", onclick: () => dismissAlert(false) }, "Not a distraction"),
        distraction.event_type === "screen" &&
          distraction.subject &&
          h("button", { class: "btn btn-sm btn-ghost", onclick: () => dismissAlert(true) }, `Always allow ${subject}`),
      ),
    );
    driftAlert.hidden = false;
  }

  function hideDriftAlert(distractionId = null) {
    if (distractionId !== null && alertDistraction?.id !== distractionId) return;
    alertDistraction = null;
    driftAlert.hidden = true;
  }

  async function dismissAlert(alwaysAllow) {
    const distraction = alertDistraction;
    if (!distraction) return;
    hideDriftAlert();
    try {
      await api.post(`/distractions/${distraction.id}/dismiss`, { always_allow: alwaysAllow });
      toast(alwaysAllow ? `Got it, ${distraction.subject} won't be flagged again.` : "Removed. Sorry about that!", "success");
    } catch (error) {
      toast(error.message, "error");
    }
  }

  // ---------- Data ----------

  async function loadToday() {
    const [sessionData, summary] = await Promise.all([
      api.get(`/sessions${query({ period: "day" })}`),
      api.get("/distractions/summary/daily"),
    ]);
    today = { sessions: sessionData.sessions, distractions: summary.total_events };
    renderToday();
  }

  let reloadTimer = null;
  function scheduleReload() {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(() => loadToday().catch((e) => toast(e.message, "error")), 300);
  }

  // The single most useful insight, as a nudge before the next session.
  async function loadTip() {
    try {
      const { items } = await api.get("/insights/recommendations");
      const top = items.find((i) => i.kind === "improve") ?? items[0];
      mount(
        tipSlot,
        top &&
          h(
            "div",
            { class: "tip-card" },
            h("div", { class: "card-header" }, h("h2", { class: "row" }, icon("bulb"), "Tip for you"), h("a", { href: "#/insights", class: "small" }, "All insights")),
            insightCard(top, { compact: true }),
          ),
      );
    } catch {
      mount(tipSlot); // the tip is optional; never block Home on it
    }
  }

  async function loadInitial() {
    [tags, settings] = await Promise.all([api.get("/tags"), api.get("/settings")]);
    renderTagOptions();
    renderFocus();
    await loadToday();
    loadTip();
  }

  // ---------- Actions ----------

  async function run(action) {
    if (busy) return;
    busy = true;
    renderFocus();
    try {
      await action();
    } catch (error) {
      toast(error.message, "error");
    } finally {
      busy = false;
      renderFocus();
    }
  }

  async function start() {
    const tagId = tagSelect.value ? Number(tagSelect.value) : null;
    saveLastTag(tagSelect.value);
    const session = await api.post("/sessions/start", { intent: intentInput.value.trim() || null, tag_id: tagId });
    intentInput.value = "";
    store.applySession(session);
  }

  async function pause() {
    store.applySession(await api.post("/sessions/pause"));
  }

  async function resume() {
    const result = await api.post("/sessions/resume");
    if (result.previous_session) {
      store.applySession(result.previous_session);
      toast("Your break ran long, so the last session was saved and a new one started.", "info", 5000);
    }
    store.applySession(result.session);
  }

  async function stop() {
    const session = await api.post("/sessions/stop");
    store.applySession(session);
    toast(`Session saved · ${formatDuration(session.duration_seconds)} · focus score ${session.focus_score}`, "success");
  }

  async function logDistraction() {
    await api.post("/distractions/manual", { reason: "Logged manually" });
    toast("Distraction logged. Back to it!");
  }

  function onMainButton() {
    const state = store.session?.status ?? "idle";
    run(state === "idle" ? start : state === "active" ? pause : resume);
  }

  // Space toggles the session, unless the user is typing.
  function onKeyDown(event) {
    if (event.code !== "Space" || event.repeat) return;
    const target = event.target;
    const interactive = "input, textarea, select, button, [contenteditable], [role=button], dialog";
    if (target instanceof HTMLElement && target.closest(interactive)) return;
    if (document.querySelector("dialog[open]")) return;
    event.preventDefault();
    onMainButton();
  }

  // ---------- Wiring ----------

  intentInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") run(start);
  });

  // Show when the desktop app has the camera open (only during an active session with the switch on).
  async function refreshCameraBadge() {
    const status = store.session?.status === "active" ? await getCameraStatus() : null;
    cameraBadge.hidden = !status?.in_use;
  }
  const cameraPoll = setInterval(refreshCameraBadge, 3000);
  cleanups.push(() => clearInterval(cameraPoll));

  const tick = setInterval(() => {
    const timer = focusButton.querySelector("[data-timer]");
    if (timer) timer.textContent = formatClock(currentFocusSeconds());
    if (store.session?.status === "paused") updatePauseNote();
    if (store.session) renderTodayNumbers();
  }, 1000);

  document.addEventListener("keydown", onKeyDown);
  cleanups.push(
    () => clearInterval(tick),
    () => clearTimeout(reloadTimer),
    () => document.removeEventListener("keydown", onKeyDown),
    store.on("session", (session) => {
      renderFocus();
      renderToday();
      if (!session || session.status !== "active") {
        renderActivity(null);
        hideDriftAlert();
      }
    }),
    store.on("sessions-changed", scheduleReload),
    store.on("session-ended", () => setTimeout(loadTip, 800)),
    store.on("distraction-logged", (distraction) => {
      scheduleReload();
      if (["screen", "camera"].includes(distraction.event_type) && store.session) showDriftAlert(distraction);
    }),
    // The agent ends a distraction (sets its duration) when the user is back on task.
    store.on("distraction-updated", (distraction) => hideDriftAlert(distraction.id)),
    store.on("distraction-dismissed", (id) => {
      hideDriftAlert(id);
      scheduleReload();
    }),
    store.on("activity", renderActivity),
  );

  renderFocus();
  loadInitial().catch((error) => toast(error.message, "error"));

  return () => cleanups.forEach((fn) => fn());
}
