const jobsBody = document.getElementById("jobs");
const proposalsBody = document.getElementById("proposals");
const summary = document.getElementById("summary");
const status = document.getElementById("status");
const runBtn = document.getElementById("run");
const impactBefore = document.getElementById("impact-before");
const impactAfter = document.getElementById("impact-after");
const impactMeta = document.getElementById("impact-meta");
const impactCats = document.getElementById("impact-cats");
const impactNote = document.getElementById("impact-note");
const wasteSummary = document.getElementById("waste-summary");
const wasteQueries = document.getElementById("waste-queries");
const wasteNote = document.getElementById("waste-note");

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
    tr.className = job.status || "";
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
    `${money(impact.recovered_usd)} recovered by proposals`;
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

async function refresh() {
  const [jobsRes, propRes, impactRes, wasteRes] = await Promise.all([
    fetch("/api/jobs"),
    fetch("/api/proposals"),
    fetch("/api/impact"),
    fetch("/api/waste"),
  ]);
  if (!jobsRes.ok || !propRes.ok || !impactRes.ok || !wasteRes.ok) {
    throw new Error("ClickHouse API failed. Check .env and that the service is awake.");
  }
  const jobs = await jobsRes.json();
  const proposals = await propRes.json();
  const impact = await impactRes.json();
  const waste = await wasteRes.json();
  renderJobs(jobs.jobs);
  renderProposals(proposals.proposals);
  renderImpact(impact);
  renderWaste(waste);
}

runBtn.addEventListener("click", async () => {
  runBtn.disabled = true;
  status.textContent = "Running detect → decide → dry-run…";
  try {
    const token = document.getElementById("token").value.trim();
    const res = await fetch("/api/run", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Run-Token": token,
      },
      body: JSON.stringify({}),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Run failed");
    summary.textContent = data.summary || "Run finished with no text.";
    renderJobs(data.jobs);
    renderProposals(data.proposals);
    renderImpact(data.impact);
    renderWaste(data.waste);
    status.textContent = "Done";
  } catch (err) {
    status.textContent = err.message;
    summary.textContent = String(err);
  } finally {
    runBtn.disabled = false;
  }
});

refresh().catch((err) => {
  status.textContent = err.message;
});
