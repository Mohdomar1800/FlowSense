// Settings: profile/timezone, focus preferences, tags, tracking rules, appearance, account and about.

import { api, setToken } from "../api.js";
import { h, icon, mount, toast } from "../dom.js";
import { getDesktopInfo, isDesktopApp, syncAgentToken } from "../desktop.js";
import { store } from "../store.js";
import { getTheme, setTheme } from "../theme.js";

export const APP_VERSION = "1.0.0";

const DEFAULT_TAG_COLOR = "#6366f1";

function timezoneOptions(current) {
  let zones = [];
  try {
    zones = Intl.supportedValuesOf("timeZone");
  } catch {
    /* older engines: fall back to the current zone only */
  }
  if (!zones.includes(current)) zones = [current, ...zones];
  if (!zones.includes("UTC")) zones = ["UTC", ...zones];
  return zones.map((zone) => h("option", { value: zone }, zone.replaceAll("_", " ")));
}

function numberField(label, { value, min, max, hint }) {
  const input = h("input", { class: "input", type: "number", min, max, step: 1, value, required: true });
  return { input, element: h("label", { class: "field" }, h("span", {}, label), input, hint && h("small", { class: "muted" }, hint)) };
}

function toggle(label, { checked, hint }) {
  const input = h("input", { type: "checkbox", role: "switch", checked });
  return {
    input,
    element: h(
      "label",
      { class: "switch" },
      h("span", {}, h("strong", {}, label), hint && h("span", { class: "small muted", style: { display: "block" } }, hint)),
      input,
    ),
  };
}

export function renderSettings(container, { logout } = {}) {
  const profileCard = h("section", { class: "card stack", "aria-label": "Profile" });
  const focusCard = h("section", { class: "card stack", "aria-label": "Focus settings" });
  const tagsCard = h("section", { class: "card stack", "aria-label": "Tags" });
  const rulesCard = h("section", { class: "card stack", "aria-label": "Screen tracking rules" });
  const appearanceCard = h("section", { class: "card stack", "aria-label": "Appearance" });
  const accountCard = h("section", { class: "card stack", "aria-label": "Account" });
  const aboutCard = h("section", { class: "card stack", "aria-label": "About" });

  mount(
    container,
    h("header", { class: "page-header" }, h("div", {}, h("h1", {}, "Settings"), h("p", { class: "muted" }, "Make FlowSense fit how you work."))),
    h(
      "div",
      { class: "settings-grid" },
      h("div", { class: "stack" }, profileCard, focusCard, appearanceCard),
      h("div", { class: "stack" }, tagsCard, rulesCard, accountCard, aboutCard),
    ),
  );

  // ---------- Appearance ----------

  function renderAppearance() {
    const current = getTheme();
    mount(
      appearanceCard,
      h("h2", {}, "Appearance"),
      h(
        "div",
        { class: "segmented", role: "radiogroup", "aria-label": "Theme" },
        [
          ["system", "System"],
          ["light", "Light"],
          ["dark", "Dark"],
        ].map(([value, label]) =>
          h(
            "button",
            {
              type: "button",
              role: "radio",
              "aria-checked": String(current === value),
              "aria-selected": String(current === value),
              onclick: () => {
                setTheme(value);
                renderAppearance();
              },
            },
            label,
          ),
        ),
      ),
      h("p", { class: "small muted" }, "System follows your computer's light or dark mode."),
    );
  }

  // ---------- Account ----------

  function renderAccount() {
    const current = h("input", { class: "input", type: "password", autocomplete: "current-password", required: true });
    const next = h("input", { class: "input", type: "password", autocomplete: "new-password", minlength: 8, required: true });
    const change = h("button", { class: "btn", type: "submit" }, "Change password");

    async function onChangePassword(event) {
      event.preventDefault();
      change.disabled = true;
      try {
        const { access_token: token } = await api.post("/auth/password", {
          current_password: current.value,
          new_password: next.value,
        });
        setToken(token);
        syncAgentToken(token);
        current.value = next.value = "";
        toast("Password changed. Other devices have been signed out.", "success");
      } catch (error) {
        toast(error.message, "error");
      } finally {
        change.disabled = false;
      }
    }

    async function onDelete() {
      const password = window.prompt(
        "This permanently deletes your account and all your sessions, distractions, reports and settings.\n\nEnter your password to confirm:",
      );
      if (!password) return;
      try {
        await api.request("DELETE", "/auth/me", { password });
        toast("Your account has been deleted.", "success");
        logout?.("Your account was deleted.");
      } catch (error) {
        toast(error.message, "error");
      }
    }

    mount(
      accountCard,
      h("h2", {}, "Account"),
      h(
        "form",
        { class: "stack", onsubmit: onChangePassword },
        h("div", { class: "form-row" }, h("label", { class: "field" }, h("span", {}, "Current password"), current), h("label", { class: "field" }, h("span", {}, "New password"), next)),
        h("div", {}, change),
      ),
      h(
        "div",
        { class: "danger-zone" },
        h("div", {}, h("strong", {}, "Delete account"), h("p", { class: "small muted" }, "Removes your account and every piece of data FlowSense has about you.")),
        h("button", { class: "btn btn-danger", type: "button", onclick: onDelete }, "Delete…"),
      ),
    );
  }

  // ---------- About ----------

  async function renderAbout() {
    const desktop = isDesktopApp() ? await getDesktopInfo() : null;
    mount(
      aboutCard,
      h("h2", {}, "About"),
      h("p", {}, `FlowSense ${APP_VERSION}`),
      h("p", { class: "small muted" }, "Your data stays in your own database. Screen titles and camera frames are processed on this computer."),
      desktop &&
        h(
          "dl",
          { class: "about-list small" },
          h("dt", {}, "Settings file"),
          h("dd", { class: "mono" }, desktop.config_file),
          h("dt", {}, "Logs"),
          h("dd", { class: "mono" }, desktop.log_dir),
        ),
    );
  }

  // ---------- Profile ----------

  function renderProfile() {
    const timezone = h("select", { class: "input" }, timezoneOptions(store.user.timezone));
    timezone.value = store.user.timezone;
    const save = h("button", { class: "btn btn-primary", type: "submit" }, "Save");

    async function onSubmit(event) {
      event.preventDefault();
      save.disabled = true;
      try {
        store.setUser(await api.patch("/auth/me", { timezone: timezone.value }));
        toast("Timezone saved", "success");
      } catch (error) {
        toast(error.message, "error");
      } finally {
        save.disabled = false;
      }
    }

    mount(
      profileCard,
      h("h2", {}, "Profile"),
      h(
        "form",
        { class: "stack", onsubmit: onSubmit },
        h("label", { class: "field" }, h("span", {}, "Email"), h("input", { class: "input", value: store.user.email, disabled: true })),
        h(
          "label",
          { class: "field" },
          h("span", {}, "Timezone"),
          timezone,
          h("small", { class: "muted" }, "Days, reports and \"best hours\" follow this timezone."),
        ),
        h("div", {}, save),
      ),
    );
  }

  // ---------- Focus settings ----------

  function renderFocusSettings(settings) {
    const pause = numberField("Long break after (minutes)", {
      value: Math.round(settings.pause_threshold_seconds / 60),
      min: 1,
      max: 120,
      hint: "Resuming after a longer break starts a new session.",
    });
    const goal = numberField("Daily focus goal (minutes)", {
      value: settings.daily_focus_goal_minutes,
      min: 0,
      max: 1440,
      hint: "0 hides the goal.",
    });
    const grace = numberField("Distraction grace period (seconds)", {
      value: settings.distraction_grace_seconds,
      min: 0,
      max: 600,
      hint: "How long off-task activity can last before it counts.",
    });
    const screen = toggle("Screen tracking", {
      checked: settings.screen_tracking_enabled,
      hint:
        "During a session, notices when you drift to off-task apps or sites and nudges you back." +
        (isDesktopApp() ? "" : " Works in the FlowSense desktop app."),
    });
    const camera = toggle("Camera tracking", {
      checked: settings.camera_tracking_enabled,
      hint:
        "During a session, notices when you pick up your phone; looking down to write notes is fine. " +
        "Video is analyzed on this computer once a second and never saved or uploaded. " +
        "The camera turns off when you pause or stop." +
        (isDesktopApp() ? "" : " Works in the FlowSense desktop app."),
    });
    const save = h("button", { class: "btn btn-primary", type: "submit" }, "Save");

    async function onSubmit(event) {
      event.preventDefault();
      save.disabled = true;
      try {
        const updated = await api.patch("/settings", {
          pause_threshold_seconds: Number(pause.input.value) * 60,
          daily_focus_goal_minutes: Number(goal.input.value),
          distraction_grace_seconds: Number(grace.input.value),
          screen_tracking_enabled: screen.input.checked,
          camera_tracking_enabled: camera.input.checked,
        });
        renderFocusSettings(updated);
        toast("Settings saved", "success");
      } catch (error) {
        toast(error.message, "error");
        save.disabled = false;
      }
    }

    mount(
      focusCard,
      h("h2", {}, "Focus"),
      h(
        "form",
        { class: "stack", onsubmit: onSubmit },
        h("div", { class: "form-row" }, pause.element, goal.element),
        grace.element,
        h("div", {}, screen.element, camera.element),
        h("div", {}, save),
      ),
    );
  }

  // ---------- Tags ----------

  function renderTags(tags) {
    const newName = h("input", { class: "input", placeholder: "New tag name", maxlength: 64, "aria-label": "New tag name" });
    const newColor = h("input", { class: "input input-color", type: "color", value: DEFAULT_TAG_COLOR, "aria-label": "New tag color" });

    async function addTag(event) {
      event.preventDefault();
      if (!newName.value.trim()) return;
      try {
        await api.post("/tags", { name: newName.value.trim(), color: newColor.value });
        await loadTags();
      } catch (error) {
        toast(error.message, "error");
      }
    }

    async function updateTag(tag, changes) {
      try {
        await api.patch(`/tags/${tag.id}`, changes);
        await loadTags();
      } catch (error) {
        toast(error.message, "error");
        await loadTags();
      }
    }

    async function deleteTag(tag) {
      if (!window.confirm(`Delete the tag "${tag.name}"? Sessions keep their history but lose the tag.`)) return;
      try {
        await api.delete(`/tags/${tag.id}`);
        await loadTags();
      } catch (error) {
        toast(error.message, "error");
      }
    }

    const rows = tags.map((tag) => {
      const name = h("input", { class: "input", value: tag.name, maxlength: 64, "aria-label": `Tag name for ${tag.name}` });
      const color = h("input", { class: "input input-color", type: "color", value: tag.color, "aria-label": `Color for ${tag.name}` });
      name.addEventListener("change", () => {
        if (name.value.trim() && name.value.trim() !== tag.name) updateTag(tag, { name: name.value.trim() });
      });
      color.addEventListener("change", () => updateTag(tag, { color: color.value }));
      return h(
        "li",
        { class: "tag-row" },
        color,
        name,
        h("button", { class: "btn btn-ghost btn-sm btn-danger", type: "button", onclick: () => deleteTag(tag), "aria-label": `Delete ${tag.name}` }, icon("trash")),
      );
    });

    mount(
      tagsCard,
      h("div", {}, h("h2", {}, "Tags"), h("p", { class: "small muted" }, "Label sessions by subject or project. Edits save automatically.")),
      tags.length ? h("ul", { class: "stack", style: { margin: 0, padding: 0, listStyle: "none", gap: "8px" } }, rows) : h("p", { class: "empty" }, "No tags yet."),
      h("form", { class: "tag-row", onsubmit: addTag }, newColor, newName, h("button", { class: "btn btn-sm", type: "submit" }, icon("plus"), "Add")),
    );
  }

  async function loadTags() {
    renderTags(await api.get("/tags"));
  }

  // ---------- Screen tracking rules ----------

  function renderRules(rules) {
    const pattern = h("input", {
      class: "input",
      placeholder: "e.g. discord, reddit, lecture",
      maxlength: 120,
      "aria-label": "Text to match",
    });
    const kind = h(
      "select",
      { class: "input", "aria-label": "Rule type", style: { width: "auto" } },
      h("option", { value: "focus" }, "Always allow"),
      h("option", { value: "distraction" }, "Always flag"),
    );

    async function addRule(event) {
      event.preventDefault();
      if (!pattern.value.trim()) return;
      try {
        await api.post("/activity/rules", { pattern: pattern.value, kind: kind.value });
        await loadRules();
      } catch (error) {
        toast(error.message, "error");
      }
    }

    async function deleteRule(rule) {
      try {
        await api.delete(`/activity/rules/${rule.id}`);
        await loadRules();
      } catch (error) {
        toast(error.message, "error");
      }
    }

    const rows = rules.map((rule) =>
      h(
        "li",
        { class: "rule-row" },
        h("span", { class: "chip", dataset: { kind: rule.kind } }, rule.kind === "focus" ? "Allow" : "Flag"),
        h("span", { class: "rule-pattern" }, rule.pattern),
        h(
          "button",
          { class: "btn btn-ghost btn-sm btn-danger", type: "button", onclick: () => deleteRule(rule), "aria-label": `Delete rule ${rule.pattern}` },
          icon("trash"),
        ),
      ),
    );

    mount(
      rulesCard,
      h(
        "div",
        {},
        h("h2", {}, "Screen tracking rules"),
        h("p", { class: "small muted" }, "Your rules win over FlowSense's built-in lists. Text is matched against the app name and window title."),
      ),
      rules.length ? h("ul", { class: "rule-list" }, rows) : h("p", { class: "empty" }, "No rules yet."),
      h("form", { class: "rule-form", onsubmit: addRule }, kind, pattern, h("button", { class: "btn btn-sm", type: "submit" }, icon("plus"), "Add")),
    );
  }

  async function loadRules() {
    renderRules(await api.get("/activity/rules"));
  }

  renderProfile();
  renderAppearance();
  renderAccount();
  renderAbout();
  mount(focusCard, h("p", { class: "loading" }, "Loading…"));
  mount(tagsCard, h("p", { class: "loading" }, "Loading…"));
  api
    .get("/settings")
    .then(renderFocusSettings)
    .catch((error) => toast(error.message, "error"));
  loadTags().catch((error) => toast(error.message, "error"));
  mount(rulesCard, h("p", { class: "loading" }, "Loading…"));
  loadRules().catch((error) => toast(error.message, "error"));
}
