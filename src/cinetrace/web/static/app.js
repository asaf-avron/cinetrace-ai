const jobsBody = document.getElementById("jobs");
const proposalsBody = document.getElementById("proposals");
const timelineEl = document.getElementById("timeline");
const status = document.getElementById("status");
const runBtn = document.getElementById("run");
const tokenRow = document.getElementById("token-row");
const impactBefore = document.getElementById("impact-before");
const impactAfter = document.getElementById("impact-after");
const impactMeta = document.getElementById("impact-meta");
const impactCats = document.getElementById("impact-cats");
const impactNote = document.getElementById("impact-note");
const impactRecovery = document.getElementById("impact-recovery");
const wasteSummary = document.getElementById("waste-summary");
const wasteQueries = document.getElementById("waste-queries");
const wasteNote = document.getElementById("waste-note");
const rollupBody = document.getElementById("rollup");
const farmSpark = document.getElementById("farm-spark");
const mcpCallsEl = document.getElementById("mcp-calls");
const mcpNote = document.getElementById("mcp-note");
const queryLogBody = document.getElementById("query-log");
const queryLogNote = document.getElementById("query-log-note");
const queryLogBadge = document.getElementById("query-log-badge");

let runPublic = false;
let highlightedJobs = new Set();

function money(value) {
  const n = Number(value);
  if (Number.isNaN(n)) return "—";
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function cell(text, tag = "td") {
  const el = document.createElement(tag);
  el.textContent = text == null ? "" : String(text);
  return el;
}

function renderJobs(jobs) {
  jobsBody.replaceChildren();
  for (const job of jobs) {
    const tr = document.createElement("tr");
    const classes = [job.status || ""];
    if (highlightedJobs.has(String(job.job_id).toLowerCase())) {
      classes.push("touched");
    }
    tr.className = classes.join(" ");
    tr.append(
      cell(job.job_id),
      cell(`${job.show} / ${job.shot}`),
      Object.assign(cell(job.status), { className: "status" }),
      cell(job.error_class),
      cell(job.retry_count),
      cell(job.queue_wait_seconds),
      cell(job.cpu_hours),
      cell(job.gpu_hours),
      cell(`${job.frames_done}/${job.frames_total}`),
    );
    jobsBody.append(tr);
  }
}

function renderProposals(proposals) {
  proposalsBody.replaceChildren();
  for (const row of proposals) {
    const tr = document.createElement("tr");
    const note = row.status === "recorded" ? row.outcome || row.reason : row.reason;
    tr.append(
      cell(row.created_at),
      cell(row.job_id),
      cell(row.action),
      Object.assign(cell(row.status), { className: row.status === "recorded" ? "recorded" : "" }),
      cell(row.mode),
      cell(row.executed ? "yes" : "no"),
      cell(note),
    );
    proposalsBody.append(tr);
  }
}

function renderImpact(impact) {
  if (!impact) return;
  impactBefore.textContent = money(impact.before_usd);
  impactAfter.textContent = money(impact.after_usd);
  const gpu = Number(impact.waste_gpu_hours || 0).toFixed(1);
  const cpu = Number(impact.waste_cpu_hours || 0).toFixed(1);
  impactMeta.textContent =
    `${gpu} GPU-h + ${cpu} CPU-h waste · ${impact.waste_job_count} of ${impact.job_count} jobs · ` +
    `${money(impact.recovered_usd)} recovered by recorded dry-runs`;
  if (impactRecovery) {
    const state = impact.recovery_state || "none";
    if (state === "full") {
      impactRecovery.textContent =
        "All waste jobs already have dry-run proposals, so “after” is $0. That is recovered waste, not a healthy farm. Reset with: python -m cinetrace.clickhouse.reset_proposals";
    } else if (state === "partial") {
      impactRecovery.textContent =
        `${money(impact.open_usd ?? impact.after_usd)} still open. Remaining jobs have no remediation_proposals row yet.`;
    } else {
      impactRecovery.textContent =
        "No dry-run proposals on waste jobs yet. Click Run supervisor to record remediations.";
    }
  }
  impactCats.replaceChildren();
  for (const cat of impact.categories || []) {
    const li = document.createElement("li");
    const label = document.createElement("strong");
    label.textContent = cat.category.replaceAll("_", " ");
    li.append(label, document.createTextNode(` ${cat.job_count} · ${money(cat.waste_usd)}`));
    impactCats.append(li);
  }
  const rate = impact.assumptions || {};
  impactNote.textContent =
    `Rates: $${Number(rate.gpu_hour_usd).toFixed(2)}/GPU-h · $${Number(rate.cpu_hour_usd).toFixed(2)}/CPU-h. ` +
    `Overrun excess vs healthy completed hours/frame. Idle queue = reserved GPU-slot hours. Seed telemetry, not a quote.`;
}

function renderWaste(waste) {
  if (!waste) return;
  if (waste.note) wasteNote.textContent = waste.note;
  wasteSummary.replaceChildren();
  wasteQueries.replaceChildren();
  for (const query of waste.queries || []) {
    const card = document.createElement("a");
    card.className = `waste-card ${query.id}`;
    card.href = `#query-${query.id}`;
    const count = document.createElement("p");
    count.className = "waste-count";
    count.textContent = String(query.count);
    const label = document.createElement("p");
    label.className = "waste-label";
    label.textContent = query.label;
    card.append(count, label);
    wasteSummary.append(card);

    const panel = document.createElement("article");
    panel.className = "query-panel";
    panel.id = `query-${query.id}`;
    const head = document.createElement("header");
    const title = document.createElement("h3");
    title.textContent = query.label;
    const badge = document.createElement("span");
    badge.className = "query-count";
    badge.textContent = `${query.count} row${query.count === 1 ? "" : "s"} · MCP ${query.mcp_tool || "run_query"}`;
    head.append(title, badge);
    const sql = document.createElement("pre");
    sql.className = "query-sql";
    sql.textContent = query.sql;
    const wrap = document.createElement("div");
    wrap.className = "table-wrap";
    const table = document.createElement("table");
    const thead = document.createElement("thead");
    const hr = document.createElement("tr");
    for (const col of query.columns || []) hr.append(cell(col, "th"));
    thead.append(hr);
    const tbody = document.createElement("tbody");
    for (const row of query.rows || []) {
      const tr = document.createElement("tr");
      for (const col of query.columns || []) tr.append(cell(row[col]));
      tbody.append(tr);
    }
    if (!(query.rows || []).length) {
      const tr = document.createElement("tr");
      const td = cell("No matching jobs");
      td.colSpan = Math.max(1, (query.columns || []).length);
      tr.append(td);
      tbody.append(tr);
    }
    table.append(thead, tbody);
    wrap.append(table);
    panel.append(head, sql, wrap);
    wasteQueries.append(panel);
  }
}

function renderRollup(rollup) {
  if (!rollupBody) return;
  rollupBody.replaceChildren();
  const days = (rollup && rollup.days) || [];
  if (farmSpark) renderSpark(days);
  if (!days.length) {
    const tr = document.createElement("tr");
    const td = cell("No farm hours yet");
    td.colSpan = 4;
    tr.append(td);
    rollupBody.append(tr);
    return;
  }
  for (const row of days) {
    const tr = document.createElement("tr");
    tr.append(
      cell(row.day),
      cell(row.jobs),
      cell(row.cpu_hours),
      cell(row.gpu_hours),
    );
    rollupBody.append(tr);
  }
}

function renderSpark(days) {
  if (!farmSpark) return;
  farmSpark.replaceChildren();
  if (!days.length) return;
  const w = 640;
  const h = 72;
  const pad = 4;
  const maxH = Math.max(...days.map((d) => Number(d.cpu_hours) + Number(d.gpu_hours)), 1);
  const barW = Math.max(8, (w - pad * 2) / days.length - 4);
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.setAttribute("class", "spark-svg");
  days.forEach((day, i) => {
    const total = Number(day.cpu_hours) + Number(day.gpu_hours);
    const bh = ((h - pad * 2) * total) / maxH;
    const rect = document.createElementNS(ns, "rect");
    rect.setAttribute("x", String(pad + i * ((w - pad * 2) / days.length)));
    rect.setAttribute("y", String(h - pad - bh));
    rect.setAttribute("width", String(barW));
    rect.setAttribute("height", String(Math.max(1, bh)));
    rect.setAttribute("class", "spark-bar");
    rect.appendChild(document.createElementNS(ns, "title")).textContent =
      `${day.day}: ${total.toFixed(1)} CPU+GPU h`;
    svg.append(rect);
  });
  farmSpark.append(svg);
}

function renderMcp(calls, server) {
  if (!mcpCallsEl) return;
  mcpCallsEl.replaceChildren();
  const rows = calls || [];
  if (mcpNote) {
    mcpNote.textContent = rows.length
      ? `${rows.length} ${server || "mcp-clickhouse"} tool call${rows.length === 1 ? "" : "s"} from this ADK run.`
      : "Click Run to capture Sentinel run_query calls from the ADK loop.";
  }
  if (!rows.length) return;
  for (const call of rows) {
    const li = document.createElement("li");
    const head = document.createElement("p");
    head.className = "mcp-head";
    const trunc = call.truncated ? " · truncated" : "";
    head.textContent = `${call.label || call.author} · ${call.tool || "run_query"} · ${call.mcp_server || "mcp-clickhouse"}${trunc}`;
    const pre = document.createElement("pre");
    pre.className = "mcp-sql";
    const args = call.args && Object.keys(call.args).length ? call.args : null;
    pre.textContent = call.query || (args ? JSON.stringify(args) : "(no query text on this tool call)");
    li.append(head, pre);
    if (call.result != null) {
      const result = document.createElement("pre");
      result.className = "mcp-result";
      result.textContent = typeof call.result === "string" ? call.result : JSON.stringify(call.result);
      li.append(result);
    }
    mcpCallsEl.append(li);
  }
}

function renderQueryLog(log) {
  if (!queryLogBody) return;
  queryLogBody.replaceChildren();
  if (queryLogNote && log && log.note) queryLogNote.textContent = log.note;
  if (queryLogBadge) {
    queryLogBadge.textContent = log && log.ok ? `${(log.rows || []).length} rows · system.query_log` : "query_log unavailable";
  }
  const rows = (log && log.rows) || [];
  if (!rows.length) {
    const tr = document.createElement("tr");
    const td = cell(log && log.ok === false ? "No query_log access on this service" : "No recent render_jobs queries");
    td.colSpan = 3;
    tr.append(td);
    queryLogBody.append(tr);
    return;
  }
  for (const row of rows) {
    const tr = document.createElement("tr");
    tr.append(cell(row.event_time), cell(row.user), cell(row.query));
    queryLogBody.append(tr);
  }
}

function renderTimeline(timeline) {
  timelineEl.replaceChildren();
  if (!timeline || !timeline.length) {
    const li = document.createElement("li");
    li.className = "timeline-empty";
    li.textContent = "No supervisor run in this session.";
    timelineEl.append(li);
    return;
  }
  for (const step of timeline) {
    const li = document.createElement("li");
    li.className = `timeline-step ${step.agent || ""}`;
    const head = document.createElement("p");
    head.className = "timeline-agent";
    head.textContent = `${step.label || step.author} · ${step.role || ""}`;
    const body = document.createElement("p");
    body.className = "timeline-text";
    body.textContent = step.text || "";
    li.append(head, body);
    if (step.job_ids && step.job_ids.length) {
      const jobs = document.createElement("p");
      jobs.className = "timeline-jobs";
      jobs.textContent = step.job_ids.join(" · ");
      li.append(jobs);
    }
    timelineEl.append(li);
  }
}

function applyRunResult(data) {
  highlightedJobs = new Set(
    (data.highlighted_job_ids || []).map((id) => String(id).toLowerCase()),
  );
  renderTimeline(data.timeline);
  renderMcp(data.mcp_calls, data.mcp_server);
  renderJobs(data.jobs);
  renderProposals(data.proposals);
  renderImpact(data.impact);
  renderWaste(data.waste);
  if (data.rollup) renderRollup(data.rollup);
  if (data.query_log) renderQueryLog(data.query_log);
}

async function refresh() {
  const [healthRes, jobsRes, propRes, impactRes, wasteRes, rollupRes, logRes] = await Promise.all([
    fetch("/api/health"),
    fetch("/api/jobs"),
    fetch("/api/proposals"),
    fetch("/api/impact"),
    fetch("/api/waste"),
    fetch("/api/rollup"),
    fetch("/api/query-log"),
  ]);
  if (healthRes.ok) {
    const health = await healthRes.json();
    runPublic = Boolean(health.run_public);
    tokenRow.hidden = runPublic;
    status.textContent = runPublic
      ? "Idle — judging mode. Run is open, limited to 5 per hour."
      : "Idle — page is public. Run spends Vertex credits and needs a demo token.";
  }
  if (!jobsRes.ok || !propRes.ok || !impactRes.ok || !wasteRes.ok || !rollupRes.ok) {
    throw new Error("ClickHouse API failed. Check .env and that the service is awake.");
  }
  const jobs = await jobsRes.json();
  const proposals = await propRes.json();
  const impact = await impactRes.json();
  const waste = await wasteRes.json();
  const rollup = await rollupRes.json();
  renderJobs(jobs.jobs);
  renderProposals(proposals.proposals);
  renderImpact(impact);
  renderWaste(waste);
  renderRollup(rollup);
  if (logRes.ok) renderQueryLog(await logRes.json());
}

runBtn.addEventListener("click", async () => {
  if (!runPublic && tokenRow.hidden) {
    tokenRow.hidden = false;
    document.getElementById("token").focus();
    status.textContent = "Paste the demo token, then click Run supervisor again.";
    return;
  }
  runBtn.disabled = true;
  status.textContent = "Running detect → decide → dry-run…";
  try {
    const token = document.getElementById("token").value.trim();
    const headers = { "Content-Type": "application/json" };
    if (token) headers["X-Run-Token"] = token;
    const res = await fetch("/api/run", {
      method: "POST",
      headers,
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Run failed");
    applyRunResult(data);
    status.textContent = "Done";
    document.getElementById("timeline").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    status.textContent = err.message;
    renderTimeline([{
      agent: "orchestrator",
      label: "Studio Orchestrator",
      role: "error",
      text: String(err),
      job_ids: [],
    }]);
  } finally {
    runBtn.disabled = false;
  }
});

refresh().catch((err) => {
  status.textContent = err.message;
});
