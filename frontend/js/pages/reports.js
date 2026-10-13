// Reports: history of daily/weekly recaps, a readable report view, Markdown export and Save as PDF.

import { api, getToken, query } from "../api.js";
import { formatDuration, h, icon, mount, scoreLevel, toast } from "../dom.js";
import { store } from "../store.js";

const PAGE_SIZE = 20;
const FILTERS = { "": "All", daily: "Daily", weekly: "Weekly" };

const parseDate = (s) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};

function fallbackTitle(report) {
  const start = parseDate(report.period_start);
  return report.report_type === "daily"
    ? start.toLocaleDateString([], { weekday: "long", month: "short", day: "numeric" })
    : `Week of ${start.toLocaleDateString([], { month: "short", day: "numeric" })}`;
}

function change(current, previous, { lowerIsBetter = false, unit = "day" } = {}) {
  if (!previous) return null;
  const delta = (current - previous) / previous;
  if (Math.abs(delta) < 0.005) return h("span", { class: "delta" }, `same as previous ${unit}`);
  const good = lowerIsBetter ? delta < 0 : delta > 0;
  return h("span", { class: "delta", dataset: { good: String(good) } }, `${delta > 0 ? "+" : ""}${Math.round(delta * 100)}% vs previous ${unit}`);
}

async function downloadMarkdown(report) {
  const response = await fetch(`/api/v1/reports/${report.id}/export`, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!response.ok) throw new Error("Export failed");
  const blob = await response.blob();
  const filename = /filename="([^"]+)"/.exec(response.headers.get("Content-Disposition") ?? "")?.[1] ?? "flowsense-report.md";
  const url = URL.createObjectURL(blob);
  const link = h("a", { href: url, download: filename, hidden: true });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast(`Saved ${filename}`, "success");
}

// ---------- report view ----------

function reportView(report, onBack) {
  const d = report.data;
  const unit = report.report_type === "daily" ? "day" : "week";
  const actions = h(
    "div",
    { class: "row report-actions no-print" },
    h("button", { class: "btn btn-sm", onclick: () => downloadMarkdown(report).catch((e) => toast(e.message, "error")) }, icon("file"), "Export Markdown"),
    h("button", { class: "btn btn-sm", onclick: () => window.print() }, icon("file"), "Save as PDF"),
  );
  const header = h(
    "header",
    { class: "report-header" },
    h("button", { class: "btn btn-ghost btn-sm report-back no-print", onclick: onBack }, "‹ All reports"),
    h("span", { class: "chip" }, report.report_type === "daily" ? "Daily report" : "Weekly report"),
    h("h2", { class: "report-title" }, d?.title ?? fallbackTitle(report)),
    h("p", { class: "muted" }, d?.summary ?? report.content),
    actions,
  );
  if (!d) return h("article", { class: "card report" }, header);

  const t = d.totals;
  const p = d.previous;
  return h(
    "article",
    { class: "card report", "aria-label": d.title },
    header,
    h(
      "div",
      { class: "kpi-row report-kpis" },
      h("div", { class: "kpi" }, h("div", { class: "kpi-label" }, "Focus time"), h("div", { class: "kpi-value" }, formatDuration(t.focus_seconds)), change(t.focus_seconds, p.focus_seconds, { unit })),
      h("div", { class: "kpi" }, h("div", { class: "kpi-label" }, "Sessions"), h("div", { class: "kpi-value" }, String(t.sessions))),
      h(
        "div",
        { class: "kpi" },
        h("div", { class: "kpi-label" }, "Focus score"),
        h("div", { class: "kpi-value" }, t.average_focus_score === null ? "–" : h("span", { class: "score", dataset: { level: scoreLevel(t.average_focus_score) } }, Math.round(t.average_focus_score))),
      ),
      h("div", { class: "kpi" }, h("div", { class: "kpi-label" }, "Distractions"), h("div", { class: "kpi-value" }, String(t.distractions)), change(t.distractions, p.distractions, { lowerIsBetter: true, unit })),
      h("div", { class: "kpi" }, h("div", { class: "kpi-label" }, "Time lost"), h("div", { class: "kpi-value" }, formatDuration(t.time_lost_seconds))),
    ),
    d.highlights.length > 0 &&
      h("section", {}, h("h3", {}, "Highlights"), h("ul", { class: "highlight-list" }, d.highlights.map((text) => h("li", {}, text)))),
    h(
      "section",
      { class: "next-goal" },
      h("h3", {}, report.report_type === "daily" ? "Goal for tomorrow" : "Goal for next week"),
      h("p", {}, d.next_goal),
    ),
    report.report_type === "weekly" && weekBars(d),
    d.top_distraction &&
      h(
        "section",
        {},
        h("h3", {}, "Biggest distraction"),
        h(
          "p",
          {},
          h("strong", {}, d.top_distraction.subject),
          `: ${d.top_distraction.count} time${d.top_distraction.count === 1 ? "" : "s"}`,
          d.top_distraction.time_lost_seconds ? `, ${formatDuration(d.top_distraction.time_lost_seconds)} lost` : "",
        ),
      ),
    d.tags.length > 0 &&
      h(
        "section",
        {},
        h("h3", {}, "Focus by tag"),
        h(
          "ul",
          { class: "bar-list" },
          d.tags.map((tag) =>
            h(
              "li",
              {},
              h("div", { class: "bar-label" }, h("span", { class: "bar-name" }, tag.name), h("span", { class: "muted small" }, formatDuration(tag.focus_seconds))),
              h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: { width: `${(100 * tag.focus_seconds) / d.tags[0].focus_seconds}%`, background: tag.color } })),
            ),
          ),
        ),
      ),
    d.on_task_share !== null && h("p", { class: "small muted" }, `${Math.round(d.on_task_share * 100)}% of tracked screen time was on task.`),
  );
}

function weekBars(d) {
  const max = Math.max(1, d.goal_seconds, ...d.days.map((day) => day.focus_seconds));
  return h(
    "section",
    {},
    h("h3", {}, "By day", d.goal_seconds ? h("span", { class: "small muted" }, ` · goal met ${d.days_goal_met} of ${d.days.length} days`) : null),
    h(
      "div",
      { class: "week-bars", role: "img", "aria-label": "Focus per day" },
      d.days.map((day) =>
        h(
          "div",
          { class: "week-bar", title: `${formatDuration(day.focus_seconds)}${day.goal_met ? " · goal met" : ""}` },
          h("div", { class: "week-bar-track" }, h("div", { class: "week-bar-fill", dataset: { goal: String(day.goal_met) }, style: { height: `${(100 * day.focus_seconds) / max}%` } })),
          h("span", { class: "small muted" }, parseDate(day.date).toLocaleDateString([], { weekday: "short" })),
        ),
      ),
    ),
  );
}

// ---------- page ----------

export function renderReports(container, { param } = {}) {
  let filter = "";
  let items = [];
  let total = 0;
  let selectedId = param ? Number(param) : null;
  let disposed = false;

  const filterTabs = h(
    "div",
    { class: "segmented no-print", role: "tablist", "aria-label": "Report type" },
    Object.entries(FILTERS).map(([value, label]) =>
      h("button", { type: "button", role: "tab", dataset: { value }, onclick: () => setFilter(value) }, label),
    ),
  );
  const list = h("ul", { class: "report-list" });
  const more = h("button", { class: "btn btn-sm btn-block", hidden: true, onclick: () => load(true) }, "Load more");
  const listPane = h("aside", { class: "card report-list-pane no-print", "aria-label": "Report history" }, list, more);
  const detail = h("div", { class: "report-detail" });
  const layout = h("div", { class: "reports-layout" }, listPane, detail);

  mount(
    container,
    h(
      "header",
      { class: "page-header no-print" },
      h("div", {}, h("h1", {}, "Reports"), h("p", { class: "muted" }, "A recap after every day and week you focus.")),
      filterTabs,
    ),
    layout,
  );

  function setFilter(value) {
    filter = value;
    load();
  }

  function select(report, { updateUrl = true } = {}) {
    selectedId = report?.id ?? null;
    layout.dataset.view = report ? "detail" : "list";
    for (const li of list.children) li.toggleAttribute("aria-current", Number(li.dataset.id) === selectedId);
    mount(detail, report ? reportView(report, () => select(null)) : h("div", { class: "card empty" }, "Select a report to read it."));
    // Keep the URL shareable without re-rendering the page (replaceState doesn't fire hashchange).
    if (updateUrl) history.replaceState(null, "", report ? `#/reports/${report.id}` : "#/reports");
  }

  function renderList() {
    for (const tab of filterTabs.children) tab.setAttribute("aria-selected", String(tab.dataset.value === filter));
    more.hidden = items.length >= total;
    if (!items.length) {
      mount(list, h("li", { class: "empty" }, "No reports yet. Your first one appears after a day with a focus session."));
      return;
    }
    mount(
      list,
      items.map((report) =>
        h(
          "li",
          { dataset: { id: String(report.id) }, "aria-current": report.id === selectedId },
          h(
            "button",
            { type: "button", class: "report-item", onclick: () => select(report) },
            h("span", { class: "report-item-title" }, report.data?.title ?? fallbackTitle(report)),
            h(
              "span",
              { class: "small muted" },
              `${report.report_type === "daily" ? "Daily" : "Weekly"} · ${formatDuration(report.data?.totals.focus_seconds ?? 0)}`,
              report.data?.totals.average_focus_score != null ? ` · score ${Math.round(report.data.totals.average_focus_score)}` : "",
            ),
          ),
        ),
      ),
    );
  }

  let latestRequest = 0;

  async function load(append = false) {
    const request = ++latestRequest; // ignore responses to superseded requests (e.g. quick filter changes)
    try {
      const page = await api.get(`/reports${query({ report_type: filter, limit: PAGE_SIZE, offset: append ? items.length : 0 })}`);
      if (disposed || request !== latestRequest) return;
      items = append ? [...items, ...page.items] : page.items;
      total = page.total_count;
      renderList();
      if (append) return;
      let selected = items.find((r) => r.id === selectedId);
      if (!selected && selectedId) {
        selected = await api.get(`/reports/${selectedId}`).catch(() => null); // a deep link to an older report
      }
      const wide = window.matchMedia("(min-width: 900px)").matches;
      select(selected ?? (wide ? items[0] ?? null : null), { updateUrl: Boolean(selected) || wide });
    } catch (error) {
      if (!disposed) toast(error.message, "error");
    }
  }

  const unsubscribe = store.on("report-created", () => load());
  load();

  return () => {
    disposed = true;
    unsubscribe();
  };
}
