// Dashboard: focus totals, trends, when you focus best, tags, distractions and screen time for a period.

import { api, query } from "../api.js";
import { loadChartJs, onThemeChange, themeColors } from "../charts.js";
import { formatDuration, h, icon, mount, scoreLevel, toast, todayIso } from "../dom.js";
import { store } from "../store.js";

const PERIOD_KEY = "flowsense.dashboardPeriod";
const PERIODS = { day: "Day", week: "Week", month: "Month" };
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const SOURCE_LABELS = { screen: "Screen", camera: "Camera", manual: "Logged", inferred: "Idle" };

// ---------- date helpers (local calendar dates as YYYY-MM-DD) ----------

const isoDate = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const parseDate = (s) => {
  const [y, m, d] = s.split("-").map(Number);
  return new Date(y, m - 1, d);
};

function shift(dateString, period, direction) {
  const d = parseDate(dateString);
  if (period === "day") d.setDate(d.getDate() + direction);
  else if (period === "week") d.setDate(d.getDate() + 7 * direction);
  else d.setMonth(d.getMonth() + direction, 1);
  return isoDate(d);
}

function rangeLabel(data) {
  const start = parseDate(data.start_date);
  const end = parseDate(data.end_date);
  if (data.period === "day") return start.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  if (data.period === "month") return start.toLocaleDateString([], { month: "long", year: "numeric" });
  const opts = { month: "short", day: "numeric" };
  return `${start.toLocaleDateString([], opts)} – ${end.toLocaleDateString([], opts)}`;
}

function readPeriod() {
  try {
    const saved = localStorage.getItem(PERIOD_KEY);
    return PERIODS[saved] ? saved : "week";
  } catch {
    return "week";
  }
}

function savePeriod(period) {
  try {
    localStorage.setItem(PERIOD_KEY, period);
  } catch {
    /* not important */
  }
}

// ---------- small pieces ----------

/** "+12% vs last week" chip. `lowerIsBetter` flips the colors (e.g. distractions). */
function delta(current, previous, { period, lowerIsBetter = false, unit = "%" } = {}) {
  if (previous === null || previous === undefined || current === null || current === undefined) return null;
  let text;
  let change;
  if (unit === "pts") {
    change = current - previous;
    if (Math.abs(change) < 0.5) return h("span", { class: "delta" }, "same as before");
    text = `${change > 0 ? "+" : ""}${Math.round(change)} pts`;
  } else {
    if (previous === 0) return current > 0 ? h("span", { class: "delta", dataset: { good: String(!lowerIsBetter) } }, "new") : null;
    change = (current - previous) / previous;
    if (Math.abs(change) < 0.005) return h("span", { class: "delta" }, "same as before");
    text = `${change > 0 ? "+" : ""}${Math.round(change * 100)}%`;
  }
  const good = lowerIsBetter ? change < 0 : change > 0;
  return h("span", { class: "delta", dataset: { good: String(good) }, title: `vs previous ${period}` }, `${text} vs last ${period}`);
}

function kpi(label, value, extra) {
  return h("div", { class: "card kpi" }, h("div", { class: "kpi-label" }, label), h("div", { class: "kpi-value" }, value), extra);
}

function emptyNote(text) {
  return h("p", { class: "empty" }, text);
}

// ---------- page ----------

export function renderDashboard(container) {
  let period = readPeriod();
  let reference = todayIso();
  let charts = [];
  let lastData = null;
  let disposed = false;

  const periodTabs = h(
    "div",
    { class: "segmented", role: "tablist", "aria-label": "Period" },
    Object.entries(PERIODS).map(([value, label]) =>
      h("button", { type: "button", role: "tab", dataset: { value }, onclick: () => setPeriod(value) }, label),
    ),
  );
  const prevButton = h("button", { class: "btn btn-ghost btn-sm", "aria-label": "Previous period", onclick: () => move(-1) }, "‹");
  const nextButton = h("button", { class: "btn btn-ghost btn-sm", "aria-label": "Next period", onclick: () => move(1) }, "›");
  const rangeText = h("span", { class: "range-label" });
  const body = h("div", { class: "dashboard" }, h("p", { class: "loading" }, "Loading…"));

  mount(
    container,
    h(
      "header",
      { class: "page-header" },
      h("div", {}, h("h1", {}, "Dashboard"), h("p", { class: "muted" }, "How your focus is going.")),
      h("div", { class: "row dashboard-controls" }, periodTabs, h("div", { class: "row" }, prevButton, rangeText, nextButton)),
    ),
    body,
  );

  function setPeriod(value) {
    period = value;
    savePeriod(value);
    reference = todayIso();
    load();
  }

  function move(direction) {
    reference = shift(reference, period, direction);
    load();
  }

  function destroyCharts() {
    charts.forEach((chart) => chart.destroy());
    charts = [];
  }

  let latestRequest = 0;

  async function load() {
    for (const tab of periodTabs.children) tab.setAttribute("aria-selected", String(tab.dataset.value === period));
    // Rapid clicks start overlapping requests; only the newest one may render, whatever order they finish in.
    const request = ++latestRequest;
    try {
      const data = await api.get(`/analytics/dashboard${query({ period, reference_date: reference })}`);
      if (disposed || request !== latestRequest) return;
      lastData = data;
      await render(data);
    } catch (error) {
      if (!disposed) mount(body, h("div", { class: "card" }, emptyNote(error.message)));
    }
  }

  // ---------- render ----------

  async function render(data) {
    rangeText.textContent = rangeLabel(data);
    nextButton.disabled = data.end_date >= todayIso();
    destroyCharts();

    const t = data.totals;
    const p = data.previous;
    if (t.sessions === 0 && t.distractions === 0) {
      mount(
        body,
        h(
          "section",
          { class: "card placeholder" },
          icon("chart"),
          h("h2", {}, "Nothing here yet"),
          h("p", { class: "muted" }, "No focus sessions in this period. Start one and your stats will appear here."),
          h("a", { class: "btn btn-primary", href: "#/home" }, "Start focusing"),
        ),
      );
      return;
    }

    const trendCanvas = h("canvas", { "aria-label": data.period === "day" ? "Focus by hour" : "Focus per day", role: "img" });
    mount(
      body,
      h(
        "div",
        { class: "kpi-row" },
        kpi("Focus time", formatDuration(t.focus_seconds), delta(t.focus_seconds, p.focus_seconds, { period: data.period })),
        kpi("Sessions", String(t.sessions), t.sessions ? h("span", { class: "muted small" }, `avg ${formatDuration(t.average_session_seconds)}`) : null),
        kpi(
          "Focus score",
          t.average_focus_score === null ? "–" : h("span", { class: "score", dataset: { level: scoreLevel(t.average_focus_score) } }, Math.round(t.average_focus_score)),
          delta(t.average_focus_score, p.average_focus_score, { period: data.period, unit: "pts" }),
        ),
        kpi("Distractions", String(t.distractions), delta(t.distractions, p.distractions, { period: data.period, lowerIsBetter: true })),
        kpi("Time lost", formatDuration(t.time_lost_seconds), h("span", { class: "muted small" }, "to distractions")),
      ),
      h(
        "div",
        { class: "dashboard-grid" },
        h(
          "section",
          { class: "card wide" },
          h("div", { class: "card-header" }, h("h2", {}, data.period === "day" ? "Focus by hour" : "Focus per day"), goalNote(data)),
          h("div", { class: "chart-box" }, trendCanvas),
        ),
        data.period !== "day" && heatmapCard(data),
        tagsCard(data),
        distractionsCard(data),
        screenTimeCard(data),
      ),
    );

    try {
      const Chart = await loadChartJs();
      if (disposed) return;
      charts.push(trendChart(Chart, trendCanvas, data));
    } catch (error) {
      toast(error.message, "error");
    }
  }

  function goalNote(data) {
    if (data.period === "day" || !data.daily_goal_seconds) return null;
    const met = data.days.filter((d) => d.goal_met).length;
    return h("span", { class: "small muted" }, `Goal met ${met} of ${data.days.length} days`);
  }

  function trendChart(Chart, canvas, data) {
    const c = themeColors();
    const hours = (seconds) => +(seconds / 3600).toFixed(2);
    const common = {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 250 },
      plugins: {
        legend: { labels: { color: c.muted, boxWidth: 12 } },
        tooltip: {
          callbacks: {
            label: (ctx) =>
              ctx.dataset.yAxisID === "score"
                ? `Focus score: ${ctx.parsed.y}`
                : `${ctx.dataset.label}: ${formatDuration(ctx.parsed.y * 3600)}`,
          },
        },
      },
      scales: {
        x: { ticks: { color: c.muted }, grid: { display: false } },
        y: {
          beginAtZero: true,
          ticks: { color: c.muted, callback: (v) => `${v}h` },
          grid: { color: c.border },
          title: { display: true, text: "Hours focused", color: c.muted },
        },
      },
    };

    if (data.period === "day") {
      return new Chart(canvas, {
        type: "bar",
        data: {
          labels: data.hours.map((x) => `${String(x.hour).padStart(2, "0")}:00`),
          datasets: [{ label: "Focused", data: data.hours.map((x) => hours(x.focus_seconds)), backgroundColor: c.accent, borderRadius: 4 }],
        },
        options: common,
      });
    }

    const labels = data.days.map((d) =>
      parseDate(d.date).toLocaleDateString([], data.period === "week" ? { weekday: "short", day: "numeric" } : { day: "numeric" }),
    );
    const datasets = [
      {
        type: "bar",
        label: "Focused",
        data: data.days.map((d) => hours(d.focus_seconds)),
        backgroundColor: data.days.map((d) => (d.goal_met ? c.success : c.accent)),
        borderRadius: 4,
        order: 2,
      },
      {
        type: "line",
        label: "Focus score",
        data: data.days.map((d) => d.average_focus_score),
        yAxisID: "score",
        borderColor: c.warning,
        backgroundColor: c.warning,
        spanGaps: true,
        tension: 0.3,
        pointRadius: 3,
        order: 1,
      },
    ];
    if (data.daily_goal_seconds) {
      datasets.push({
        type: "line",
        label: "Daily goal",
        data: data.days.map(() => hours(data.daily_goal_seconds)),
        borderColor: c.muted,
        borderDash: [6, 4],
        borderWidth: 1.5,
        pointRadius: 0,
        order: 0,
      });
    }
    return new Chart(canvas, {
      data: { labels, datasets },
      options: {
        ...common,
        scales: {
          ...common.scales,
          score: { position: "right", min: 0, max: 100, ticks: { color: c.muted }, grid: { display: false }, title: { display: true, text: "Score", color: c.muted } },
        },
      },
    });
  }

  function heatmapCard(data) {
    const max = Math.max(1, ...data.heatmap.map((c) => c.focus_seconds));
    const cells = new Map(data.heatmap.map((c) => [`${c.weekday}-${c.hour}`, c.focus_seconds]));
    const best = data.heatmap.length ? data.heatmap.reduce((a, b) => (b.focus_seconds > a.focus_seconds ? b : a)) : null;

    const grid = h("div", { class: "heatmap", role: "img", "aria-label": "Focus by weekday and hour" });
    grid.append(h("span", {}));
    for (let hour = 0; hour < 24; hour++) grid.append(h("span", { class: "heat-hour" }, hour % 3 === 0 ? String(hour) : ""));
    WEEKDAYS.forEach((day, weekday) => {
      grid.append(h("span", { class: "heat-day" }, day));
      for (let hour = 0; hour < 24; hour++) {
        const seconds = cells.get(`${weekday}-${hour}`) ?? 0;
        grid.append(
          h("span", {
            class: "heat-cell",
            style: { opacity: seconds ? String(0.15 + 0.85 * (seconds / max)) : "" },
            dataset: { empty: String(!seconds) },
            title: `${day} ${String(hour).padStart(2, "0")}:00 · ${formatDuration(seconds)}`,
          }),
        );
      }
    });

    return h(
      "section",
      { class: "card wide" },
      h(
        "div",
        { class: "card-header" },
        h("h2", {}, "When you focus"),
        best && h("span", { class: "small muted" }, `Most focused: ${WEEKDAYS[best.weekday]} around ${String(best.hour).padStart(2, "0")}:00`),
      ),
      grid,
    );
  }

  function barList(items, { valueText, color }) {
    const max = Math.max(1, ...items.map((i) => i.value));
    return h(
      "ul",
      { class: "bar-list" },
      items.map((item) =>
        h(
          "li",
          {},
          h("div", { class: "bar-label" }, h("span", { class: "bar-name", title: item.label }, item.label), h("span", { class: "muted small" }, valueText(item))),
          h("div", { class: "bar-track" }, h("div", { class: "bar-fill", style: { width: `${(100 * item.value) / max}%`, background: color(item) } })),
        ),
      ),
    );
  }

  function tagsCard(data) {
    return h(
      "section",
      { class: "card" },
      h("h2", { class: "card-title" }, "Focus by tag"),
      data.tags.length
        ? barList(
            data.tags.map((t) => ({ label: t.name, value: t.focus_seconds, color: t.color })),
            { valueText: (i) => formatDuration(i.value), color: (i) => i.color },
          )
        : emptyNote("No focus time yet."),
    );
  }

  function distractionsCard(data) {
    return h(
      "section",
      { class: "card" },
      h("h2", { class: "card-title" }, "Top distractions"),
      data.top_distractions.length
        ? h(
            "ul",
            { class: "distraction-list" },
            data.top_distractions.map((d) =>
              h(
                "li",
                {},
                h("span", { class: "bar-name" }, d.subject),
                h("span", { class: "chip" }, SOURCE_LABELS[d.source] ?? d.source),
                h("span", { class: "muted small" }, `${d.count}×${d.time_lost_seconds ? ` · ${formatDuration(d.time_lost_seconds)}` : ""}`),
              ),
            ),
          )
        : emptyNote("No distractions. Nice!"),
    );
  }

  function screenTimeCard(data) {
    const s = data.screen_time;
    const total = s.focus + s.neutral + s.distracting;
    const c = themeColors();
    const colors = { focus: c.success, neutral: c.muted, distracting: c.danger };
    if (!total) {
      return h(
        "section",
        { class: "card" },
        h("h2", { class: "card-title" }, "Screen time"),
        emptyNote("No screen activity recorded in this period. The desktop app records it during sessions when screen tracking is on."),
      );
    }
    const segment = (key, label) =>
      s[key] ? h("div", { style: { width: `${(100 * s[key]) / total}%`, background: colors[key] }, title: `${label}: ${formatDuration(s[key])}` }) : null;
    return h(
      "section",
      { class: "card" },
      h("h2", { class: "card-title" }, "Screen time"),
      h("div", { class: "stacked-bar" }, segment("focus", "On task"), segment("neutral", "Neutral"), segment("distracting", "Off task")),
      h(
        "p",
        { class: "small muted" },
        `${Math.round((100 * s.focus) / total)}% on task · ${Math.round((100 * s.distracting) / total)}% off task`,
      ),
      barList(
        data.top_activities.map((a) => ({ label: a.subject, value: a.seconds, category: a.category })),
        { valueText: (i) => formatDuration(i.value), color: (i) => colors[i.category] },
      ),
    );
  }

  // ---------- live refresh ----------

  let reloadTimer = null;
  const scheduleReload = () => {
    clearTimeout(reloadTimer);
    reloadTimer = setTimeout(load, 500);
  };
  const unsubscribers = [
    store.on("sessions-changed", scheduleReload),
    store.on("distraction-logged", scheduleReload),
    onThemeChange(() => lastData && render(lastData)),
  ];
  // While a session runs, its numbers change; refresh every minute.
  const ticker = setInterval(() => store.session?.status === "active" && load(), 60_000);

  load();

  return () => {
    disposed = true;
    destroyCharts();
    clearTimeout(reloadTimer);
    clearInterval(ticker);
    unsubscribers.forEach((fn) => fn());
  };
}
