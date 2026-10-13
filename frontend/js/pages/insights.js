// Insights: personal, evidence-backed tips from the last four weeks.

import { api } from "../api.js";
import { h, icon, mount, toast } from "../dom.js";
import { store } from "../store.js";

const SECTIONS = [
  { kind: "improve", title: "Work on", iconName: "bulb" },
  { kind: "strength", title: "Keep it up", iconName: "chart" },
  { kind: "info", title: "Good to know", iconName: "file" },
];
const CONFIDENCE_LABELS = { high: "High confidence", medium: "Medium confidence", low: "Early signal" };

export function insightCard(item, { compact = false } = {}) {
  return h(
    "article",
    { class: "card insight", dataset: { kind: item.kind } },
    h("h3", { class: "insight-title" }, item.title),
    h("p", {}, item.message),
    item.tip && h("p", { class: "insight-tip" }, h("strong", {}, "Try this: "), item.tip),
    !compact &&
      h(
        "p",
        { class: "insight-evidence small muted" },
        h("span", {}, item.evidence),
        h("span", { class: "chip", dataset: { confidence: item.confidence } }, CONFIDENCE_LABELS[item.confidence]),
      ),
  );
}

export function renderInsights(container) {
  const summary = h("p", { class: "muted" }, "Looking at your recent sessions…");
  const body = h("div", { class: "stack" }, h("p", { class: "loading" }, "Loading…"));
  mount(container, h("header", { class: "page-header" }, h("div", {}, h("h1", {}, "Insights"), summary)), body);

  let disposed = false;

  async function load() {
    try {
      const data = await api.get("/insights/recommendations");
      if (disposed) return;
      summary.textContent = data.sessions_analyzed
        ? `Based on ${data.sessions_analyzed} session${data.sessions_analyzed === 1 ? "" : "s"} from the last ${data.lookback_days} days.`
        : "Personal tips will appear here as you use FlowSense.";
      mount(
        body,
        SECTIONS.map(({ kind, title, iconName }) => {
          const items = data.items.filter((item) => item.kind === kind);
          if (!items.length) return null;
          return h(
            "section",
            { class: "insight-section", "aria-label": title },
            h("h2", { class: "row" }, icon(iconName), title),
            h("div", { class: "insight-grid" }, items.map((item) => insightCard(item))),
          );
        }),
      );
    } catch (error) {
      if (!disposed) toast(error.message, "error");
    }
  }

  let timer = null;
  const unsubscribe = store.on("sessions-changed", () => {
    clearTimeout(timer);
    timer = setTimeout(load, 800);
  });
  load();

  return () => {
    disposed = true;
    clearTimeout(timer);
    unsubscribe();
  };
}
