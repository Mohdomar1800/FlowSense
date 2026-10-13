// First-run setup for new accounts: daily goal, first tags, and tracking choices. Can be skipped.

import { api } from "../api.js";
import { isDesktopApp } from "../desktop.js";
import { h, mount, toast } from "../dom.js";

const GOALS = [30, 60, 120, 180];
const TAG_SUGGESTIONS = [
  { name: "Study", color: "#10b981" },
  { name: "Coding", color: "#6366f1" },
  { name: "Reading", color: "#f59e0b" },
  { name: "Writing", color: "#ec4899" },
  { name: "Work", color: "#0ea5e9" },
];

export function renderOnboarding(root, { onDone }) {
  const state = {
    step: 0,
    goal: 120,
    tags: new Set(["Study"]),
    screen: true,
    camera: false,
  };
  const card = h("div", { class: "card onboarding-card stack" });
  mount(
    root,
    h(
      "div",
      { class: "auth onboarding" },
      h("div", { class: "brand" }, h("img", { src: "assets/icon.svg", alt: "" }), "FlowSense"),
      card,
    ),
  );

  const steps = [welcomeStep, goalStep, tagsStep, trackingStep];

  function progress() {
    return h(
      "div",
      { class: "onboarding-progress", "aria-label": `Step ${state.step + 1} of ${steps.length}` },
      steps.map((_, i) => h("span", { dataset: { done: String(i <= state.step) } })),
    );
  }

  function nav({ next = "Next", onNext = () => go(1) } = {}) {
    return h(
      "div",
      { class: "row onboarding-nav" },
      state.step > 0 ? h("button", { class: "btn btn-ghost", onclick: () => go(-1) }, "Back") : h("span", {}),
      h("span", { class: "spacer" }),
      h("button", { class: "link-button small", onclick: skip }, "Skip setup"),
      h("button", { class: "btn btn-primary", onclick: onNext }, next),
    );
  }

  function go(delta) {
    state.step = Math.max(0, Math.min(steps.length - 1, state.step + delta));
    render();
  }

  function render() {
    mount(card, progress(), steps[state.step]());
    card.querySelector("button.btn-primary")?.focus();
  }

  // ---------- steps ----------

  function welcomeStep() {
    return [
      h("h2", {}, "Welcome to FlowSense"),
      h("p", { class: "muted" }, "Three quick choices and you're ready for your first focus session. You can change all of them later in Settings."),
      h(
        "ul",
        { class: "highlight-list" },
        h("li", {}, "Press one big button to start focusing."),
        h("li", {}, "FlowSense notices when you drift and nudges you back."),
        h("li", {}, "Every day and week you get a recap with one goal to work on."),
      ),
      nav({ next: "Let's go" }),
    ];
  }

  function goalStep() {
    const choices = h(
      "div",
      { class: "choice-grid", role: "radiogroup", "aria-label": "Daily focus goal" },
      GOALS.map((minutes) =>
        h(
          "button",
          {
            type: "button",
            class: "choice",
            role: "radio",
            "aria-checked": String(state.goal === minutes),
            onclick: () => {
              state.goal = minutes;
              render();
            },
          },
          h("strong", {}, minutes < 60 ? `${minutes} min` : `${minutes / 60} h`),
          h("span", { class: "small muted" }, { 30: "Getting started", 60: "Steady habit", 120: "Serious study", 180: "Deep work days" }[minutes]),
        ),
      ),
    );
    return [
      h("h2", {}, "How much focused time do you want each day?"),
      h("p", { class: "muted" }, "Your daily goal. Start small: hitting it every day builds the habit."),
      choices,
      nav(),
    ];
  }

  function tagsStep() {
    const custom = h("input", { class: "input", placeholder: "Add your own", maxlength: 64, "aria-label": "Custom tag" });
    const addCustom = () => {
      const name = custom.value.trim();
      if (name) {
        state.tags.add(name);
        render();
      }
    };
    custom.addEventListener("keydown", (event) => {
      if (event.key === "Enter") addCustom();
    });
    const names = [...new Set([...TAG_SUGGESTIONS.map((t) => t.name), ...state.tags])];
    return [
      h("h2", {}, "What do you focus on?"),
      h("p", { class: "muted" }, "Tags let you see where your time goes. Pick a few, or add your own."),
      h(
        "div",
        { class: "tag-picker" },
        names.map((name) =>
          h(
            "button",
            {
              type: "button",
              class: "chip chip-toggle",
              "aria-pressed": String(state.tags.has(name)),
              onclick: () => {
                if (state.tags.has(name)) state.tags.delete(name);
                else state.tags.add(name);
                render();
              },
            },
            name,
          ),
        ),
      ),
      h("div", { class: "row" }, custom, h("button", { class: "btn btn-sm", type: "button", onclick: addCustom }, "Add")),
      nav(),
    ];
  }

  function trackingStep() {
    const option = (key, title, text) => {
      const input = h("input", { type: "checkbox", role: "switch", checked: state[key] });
      input.addEventListener("change", () => (state[key] = input.checked));
      return h("label", { class: "switch tracking-option" }, h("span", {}, h("strong", {}, title), h("span", { class: "small muted", style: { display: "block" } }, text)), input);
    };
    return [
      h("h2", {}, "Should FlowSense keep you on track?"),
      h(
        "p",
        { class: "muted" },
        "Both run only while a session is active, and everything stays on this computer." +
          (isDesktopApp() ? "" : " They work in the FlowSense desktop app."),
      ),
      option("screen", "Screen tracking", "Notices when you drift to off-task apps or sites. Only the app name and window title are used; no screenshots."),
      option("camera", "Camera tracking", "Notices when you pick up your phone. Looking down to write notes is fine. Video is never saved or uploaded."),
      nav({ next: "Finish", onNext: finish }),
    ];
  }

  // ---------- saving ----------

  async function markOnboarded() {
    return api.patch("/auth/me", { onboarded: true });
  }

  async function finish() {
    card.querySelectorAll("button").forEach((b) => (b.disabled = true));
    try {
      await api.patch("/settings", {
        daily_focus_goal_minutes: state.goal,
        screen_tracking_enabled: state.screen,
        camera_tracking_enabled: state.camera,
      });
      for (const name of state.tags) {
        const color = TAG_SUGGESTIONS.find((t) => t.name === name)?.color ?? "#6366f1";
        await api.post("/tags", { name, color }).catch((error) => {
          if (error.status !== 409) throw error; // an existing tag with that name is fine
        });
      }
      const user = await markOnboarded();
      toast("You're all set. Press Start when you're ready!", "success");
      onDone(user);
    } catch (error) {
      toast(error.message, "error");
      card.querySelectorAll("button").forEach((b) => (b.disabled = false));
    }
  }

  async function skip() {
    try {
      onDone(await markOnboarded());
    } catch (error) {
      toast(error.message, "error");
    }
  }

  render();
}
