// Session details: timeline, edit name/tag, delete. Uses the native <dialog> (focus handling, Esc to close).

import { api } from "../api.js";
import { formatDuration, formatTime, h, mount, scoreLevel, toast } from "../dom.js";

const TIMELINE_LABELS = {
  started: "Started",
  paused: "Paused",
  resumed: "Resumed",
  stopped: "Stopped",
  distraction: "Distraction",
};

function timelineText(item) {
  const d = item.details ?? {};
  if (item.kind === "distraction") return d.reason ? `${d.reason}` : "Distraction";
  if (item.kind === "resumed" && d.pause_seconds) return `Resumed after a ${formatDuration(d.pause_seconds)} break`;
  if (item.kind === "stopped" && d.reason === "long_pause") return "Ended by a long break";
  if (item.kind === "started" && d.split_from) return "Started after a long break";
  return TIMELINE_LABELS[item.kind] ?? item.kind;
}

export async function openSessionDialog(sessionId, tags) {
  let session;
  try {
    session = await api.get(`/sessions/${sessionId}`);
  } catch (error) {
    toast(error.message, "error");
    return;
  }

  const dialog = h("dialog", { class: "dialog", "aria-labelledby": "session-dialog-title" });
  const close = () => dialog.close();
  dialog.addEventListener("close", () => dialog.remove());
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) close(); // click on the backdrop
  });

  const intent = h("input", { class: "input", value: session.intent ?? "", maxlength: 200, placeholder: "What were you working on?" });
  const tag = h(
    "select",
    { class: "input" },
    h("option", { value: "" }, "No tag"),
    tags.map((t) => h("option", { value: String(t.id) }, t.name)),
  );
  tag.value = session.tag_id ? String(session.tag_id) : "";

  async function save(event) {
    event.preventDefault();
    try {
      await api.patch(`/sessions/${session.id}`, {
        intent: intent.value.trim() || null,
        tag_id: tag.value ? Number(tag.value) : null,
      });
      toast("Session updated", "success");
      close();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  async function remove() {
    if (!window.confirm("Delete this session and its distractions? This can't be undone.")) return;
    try {
      await api.delete(`/sessions/${session.id}`);
      toast("Session deleted", "success");
      close();
    } catch (error) {
      toast(error.message, "error");
    }
  }

  const open = session.status !== "ended";
  mount(
    dialog,
    h(
      "form",
      { class: "stack", onsubmit: save },
      h(
        "div",
        { class: "dialog-header" },
        h("h2", { id: "session-dialog-title" }, session.intent || tags.find((t) => t.id === session.tag_id)?.name || "Focus session"),
        h("button", { type: "button", class: "btn btn-ghost btn-sm", "aria-label": "Close", onclick: close }, "✕"),
      ),
      h(
        "div",
        { class: "metric-row" },
        h("div", { class: "metric" }, h("div", { class: "metric-value" }, formatDuration(session.duration_seconds)), h("div", { class: "metric-label" }, "Focused")),
        h(
          "div",
          { class: "metric" },
          h("div", { class: "metric-value score", dataset: { level: scoreLevel(session.focus_score) } }, String(session.focus_score)),
          h("div", { class: "metric-label" }, open ? "Score so far" : "Focus score"),
        ),
        h("div", { class: "metric" }, h("div", { class: "metric-value" }, String(session.distraction_count)), h("div", { class: "metric-label" }, "Distractions")),
      ),
      h("h3", {}, "Timeline"),
      h(
        "ol",
        { class: "timeline" },
        session.timeline.map((item) =>
          h("li", { dataset: { kind: item.kind } }, h("span", { class: "mono small muted" }, formatTime(item.timestamp)), h("span", {}, timelineText(item))),
        ),
      ),
      h("label", { class: "field" }, h("span", {}, "Working on"), intent),
      h("label", { class: "field" }, h("span", {}, "Tag"), tag),
      h(
        "div",
        { class: "row dialog-actions" },
        h("button", { type: "button", class: "btn btn-ghost btn-danger", onclick: remove }, "Delete session"),
        h("span", { class: "spacer" }),
        h("button", { type: "button", class: "btn", onclick: close }, "Cancel"),
        h("button", { type: "submit", class: "btn btn-primary" }, "Save"),
      ),
    ),
  );
  document.body.append(dialog);
  dialog.showModal();
}
