"use strict";

// Supervisor page. Every panel renders straight from a ClickHouse query and
// carries the cost of that query, because on this track the interesting claim
// is not "we have a dashboard" but "this scanned a quarter-billion rows and came
// back in under a second".

const $ = (id) => document.getElementById(id);

const state = {
  highlighted: new Set(),
  running: false,
  runStarted: 0,
  tick: null,
  mcpCalls: [],
  sentinelPasses: 0,
  engine: null,
};

// ---------------------------------------------------------------- formatting

const nf = new Intl.NumberFormat("en-US");

function money(value) {
  const n = Number(value || 0);
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `$${nf.format(Math.round(n))}`;
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function compact(value) {
  const n = Number(value || 0);
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}k`;
  return nf.format(n);
}

function statBadge(stats) {
  if (!stats || !stats.rows_read) return "";
  const rate = stats.rows_per_sec
    ? ` &middot; ${compact(stats.rows_per_sec)} rows/s`
    : "";
  return `scanned ${compact(stats.rows_read)} rows in ${stats.elapsed_ms}ms${rate}`;
}

function setBadge(id, stats) {
  const el = $(id);
  if (el) el.innerHTML = statBadge(stats);
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

// Models answer in markdown. Rendering it as literal `**job-zombie**` makes a
// correct answer look scruffy. Escape first, then allow exactly bold, inline
// code and bullets -- nothing that could smuggle markup through.
function mdLite(text) {
  const lines = esc(text).split("\n");
  let html = "";
  let inList = false;
  for (const raw of lines) {
    const line = raw.trim();
    const bullet = line.match(/^[*-]\s+(.*)$/);
    if (bullet) {
      if (!inList) { html += "<ul>"; inList = true; }
      html += `<li>${bullet[1]}</li>`;
      continue;
    }
    if (inList) { html += "</ul>"; inList = false; }
    if (line) html += `<p>${line}</p>`;
  }
  if (inList) html += "</ul>";
  return html
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>");
}

function shortTime(value) {
  if (!value) return "—";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value).slice(0, 16);
  return d.toISOString().slice(5, 16).replace("T", " ");
}

function hours(value) {
  const n = Number(value || 0);
  return n >= 10 ? `${n.toFixed(0)}h` : `${n.toFixed(1)}h`;
}

async function getJSON(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`${url} -> ${response.status}`);
  return response.json();
}

// ------------------------------------------------------------------- scale

function renderScale(scale) {
  if (!scale) return;
  $("scale-samples").textContent = compact(scale.samples);
  $("scale-jobs").textContent = compact(scale.jobs);
  $("scale-hosts").textContent = nf.format(scale.hosts || 0);
  $("scale-days").textContent = nf.format(scale.days_of_history || 0);
  $("scale-size").textContent = `${((scale.samples_mb || 0) / 1024).toFixed(1)} GB`;
  $("scale-rollup").textContent = compact(scale.rollup_rows);
}

// ------------------------------------------------------------------ dailies

function renderShots(data) {
  if (!data) return;
  const atRisk = data.at_risk_count || 0;
  const recoverable = data.recoverable_count || 0;
  $("shots-at-risk").textContent = atRisk;
  $("shots-recoverable").textContent = recoverable;
  $("slots-stuck").textContent = data.slots_stuck || 0;

  const shows = (data.shows_at_risk || []).join(", ");
  $("dailies-lead").innerHTML = atRisk
    ? `Earliest-deadline-first projection across ${data.tracked_count} tracked shots. ` +
      `${atRisk} will miss review on ${esc(shows)}; ${recoverable} come back inside the ` +
      `deadline if the ${data.slots_stuck} stuck GPU slots are released now.`
    : `All ${data.tracked_count} tracked shots are currently projected to make their review.`;

  const rows = (data.rows || []).filter((r) => r.at_risk).slice(0, 6);
  $("shot-cards").innerHTML = rows.length
    ? rows.map((r) => `
      <article class="shot-card ${r.recoverable ? "recoverable" : "lost"}">
        <header>
          <span class="shot-show">${esc(r.show)}</span>
          <span class="shot-id">${esc(r.shot)}</span>
          <span class="shot-priority ${esc(r.priority)}">${esc(r.priority)}</span>
        </header>
        <p class="shot-countdown">review in <strong>${hours(r.hours_to_review)}</strong></p>
        <dl class="shot-facts">
          <div><dt>frames left</dt><dd>${nf.format(r.frames_remaining)}</dd></div>
          <div><dt>finishes in</dt><dd class="bad">${hours(r.eta_hours_now)}</dd></div>
          <div><dt>if slots freed</dt><dd class="${r.recoverable ? "good" : ""}">${hours(r.eta_hours_recovered)}</dd></div>
        </dl>
        <p class="shot-verdict">${r.recoverable
          ? `Recoverable &mdash; freeing ${r.slots_recovered - r.slots_now} slots on ${esc(r.show)} makes the review.`
          : "Not recoverable by freeing slots alone; needs scope or schedule."}</p>
      </article>`).join("")
    : `<p class="empty">Nothing at risk right now. The farm is ahead of every review.</p>`;

  $("shots-sql").textContent = data.sql || "";
  setBadge("shots-stats", data.stats);
}

// ------------------------------------------------------------------- impact

function renderImpact(impact) {
  if (!impact) return;
  const open = impact.open || {};
  const hist = impact.historical || {};

  $("impact-open").textContent = money(open.remaining_usd);
  $("impact-open-sub").textContent =
    `${nf.format(open.job_count || 0)} open jobs · ${nf.format(Math.round(open.gpu_hours || 0))} GPU-h · ${nf.format(Math.round(open.cpu_hours || 0))} CPU-h`;

  $("impact-approved").textContent = money(open.approved_usd);
  $("impact-approved-sub").textContent = open.approved_jobs
    ? `${open.approved_jobs} approved · ${open.pending_jobs || 0} awaiting a decision`
    : (open.pending_jobs
        ? `${open.pending_jobs} proposal(s) awaiting approval — approve below to move this number`
        : "No proposals yet. Run the supervisor.");

  $("impact-history").textContent = money(hist.usd);
  $("impact-history-sub").textContent =
    `${nf.format(hist.job_count || 0)} wasteful jobs out of ${nf.format(hist.total_jobs || 0)} · ` +
    `${money(hist.annualized_usd)} annualised`;

  const a = impact.assumptions || {};
  $("impact-note").textContent =
    `GPU-hour $${a.gpu_hour_usd} · CPU-hour $${a.cpu_hour_usd}. Overruns priced against ${a.overrun_baseline}. ` +
    `One waste class per job, so nothing is double counted. Rates are a studio-lot estimate, not a vendor quote.`;

  const cats = impact.categories || [];
  $("waste-summary").innerHTML = cats.map((c) => `
    <a class="waste-chip" href="#panel-${esc(c.category)}">
      <span class="waste-count">${nf.format(c.open_count)}</span>
      <span class="waste-name">${esc(c.category.replace("_", " "))}</span>
      <span class="waste-usd">${money(c.open_usd)} open</span>
      <span class="waste-total">${money(c.waste_usd)} in 90d</span>
    </a>`).join("");
}

// ----------------------------------------------------------------- detection

function renderWaste(data) {
  if (!data) return;
  $("waste-queries").innerHTML = (data.queries || []).map((q) => `
    <article class="query-panel" id="panel-${esc(q.id)}">
      <header>
        <h3>${esc(q.label)}</h3>
        <span class="query-count">${q.count} row${q.count === 1 ? "" : "s"}</span>
      </header>
      <p class="panel-lead">${esc(q.note)} <span class="stat-badge">${statBadge(q.stats)}</span></p>
      <pre><code>${esc(q.sql)}</code></pre>
      ${renderTable(q.columns, q.rows)}
    </article>`).join("");
}

function renderTable(columns, rows) {
  if (!rows || !rows.length) return `<p class="empty">No rows.</p>`;
  const head = columns.map((c) => `<th>${esc(c)}</th>`).join("");
  const body = rows.slice(0, 12).map((row) => {
    const hot = state.highlighted.has(String(row.job_id || "").toLowerCase());
    const cells = columns.map((c) => `<td>${esc(row[c])}</td>`).join("");
    return `<tr class="${hot ? "hit" : ""}">${cells}</tr>`;
  }).join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

// ---------------------------------------------------------------- root cause

function renderRootCause(data) {
  if (!data) return;
  const asof = data.asof || {};
  $("asof-rows").innerHTML = (asof.rows || []).map((r) => `
    <tr class="${state.highlighted.has(String(r.job_id).toLowerCase()) ? "hit" : ""}">
      <td class="mono">${esc(r.job_id)}</td>
      <td>${esc(r.show)} / ${esc(r.shot)}</td>
      <td class="mono">${esc(r.host)}</td>
      <td><span class="vram ${r.vram_pct >= 90 ? "critical" : ""}">${r.vram_pct}%</span>
          <span class="dim">${compact(r.vram_used_mb)} / ${compact(r.vram_total_mb)} MB</span></td>
      <td>${r.seconds_before_death}s before death</td>
      <td>${nf.format(r.last_frame)}</td>
    </tr>`).join("") || `<tr><td colspan="6" class="empty">No OOM failures in the last 48 hours.</td></tr>`;
  $("asof-sql").textContent = asof.sql || "";
  setBadge("asof-stats", asof.stats);

  const storms = data.storms || {};
  $("storm-rows").innerHTML = (storms.rows || []).map((r) => `
    <tr>
      <td class="mono">${esc(r.host)}</td>
      <td>${esc(r.show)}</td>
      <td class="mono">${esc(r.job_id)}</td>
      <td>${esc(r.error_class)}</td>
      <td>${r.minutes_since_prev} min after the previous failure</td>
    </tr>`).join("") || `<tr><td colspan="5" class="empty">No repeat failures inside 90 minutes.</td></tr>`;
}

// -------------------------------------------------------------------- recall

async function runRecall(event) {
  if (event) event.preventDefault();
  const query = $("recall-input").value.trim();
  if (query.length < 4) return;
  $("recall-results").innerHTML = `<li class="empty">Embedding the query with Vertex AI…</li>`;
  try {
    const data = await getJSON(`/api/similar?q=${encodeURIComponent(query)}`);
    setBadge("recall-stats", data.stats);
    $("recall-results").innerHTML = (data.matches || []).map((m) => `
      <li class="recall-item">
        <div class="recall-score">${(m.similarity * 100).toFixed(1)}%</div>
        <div>
          <p class="recall-text">${esc(m.error_text)}</p>
          <p class="recall-fix"><span class="recall-tag">${esc(m.error_class)}</span> ${esc(m.resolution)}</p>
        </div>
      </li>`).join("");
  } catch (err) {
    $("recall-results").innerHTML = `<li class="empty">Search unavailable: ${esc(err.message)}</li>`;
  }
}

// --------------------------------------------------------------------- farm

function renderRollup(data) {
  if (!data) return;
  const days = data.days || [];
  $("rollup").innerHTML = days.slice(-14).map((d) => `
    <tr><td>${esc(d.day)}</td><td>${nf.format(d.jobs)}</td>
        <td>${nf.format(Math.round(d.cpu_hours))}</td><td>${nf.format(Math.round(d.gpu_hours))}</td></tr>`).join("");
  setBadge("timeline-stats", (data.timeline || {}).stats);
  drawSpark(days);
}

function drawSpark(days) {
  const host = $("farm-spark");
  if (!host || !days.length) return;
  const width = 960;
  const height = 90;
  const max = Math.max(...days.map((d) => Number(d.gpu_hours) || 0), 1);
  const step = width / Math.max(days.length - 1, 1);
  const points = days.map((d, i) =>
    `${(i * step).toFixed(1)},${(height - (Number(d.gpu_hours) / max) * (height - 8)).toFixed(1)}`);
  host.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="GPU hours by day">
      <polyline points="${points.join(" ")}" fill="none" stroke="currentColor" stroke-width="2" />
      <polygon points="0,${height} ${points.join(" ")} ${width},${height}" fill="currentColor" opacity="0.12" />
    </svg>`;
}

function renderJobs(jobs) {
  $("jobs").innerHTML = (jobs || []).map((j) => `
    <tr class="${state.highlighted.has(String(j.job_id).toLowerCase()) ? "hit" : ""}">
      <td class="mono">${esc(j.job_id)}</td>
      <td>${esc(j.show)} / ${esc(j.shot)}</td>
      <td><span class="pill ${esc(j.status)}">${esc(j.status)}</span></td>
      <td>${j.waste_class === "healthy" ? '<span class="dim">—</span>' : `<span class="pill waste">${esc(j.waste_class)}</span>`}</td>
      <td>${esc(j.error_class) || '<span class="dim">—</span>'}</td>
      <td>${j.retry_count}</td>
      <td>${j.cpu_hours}</td>
      <td>${j.gpu_hours}</td>
      <td>${nf.format(j.frames_done)}/${nf.format(j.frames_total)}</td>
      <td>${Number(j.waste_usd) > 0 ? `<strong>${money(j.waste_usd)}</strong>` : '<span class="dim">—</span>'}</td>
    </tr>`).join("") || `<tr><td colspan="10" class="empty">No live jobs.</td></tr>`;
}

function renderProposals(proposals) {
  $("proposals").innerHTML = (proposals || []).map((p) => {
    const pending = p.decision === "pending";
    return `
    <tr class="${state.highlighted.has(String(p.job_id).toLowerCase()) ? "hit" : ""}">
      <td>${shortTime(p.created_at)}</td>
      <td class="mono">${esc(p.job_id)}</td>
      <td><span class="pill action">${esc(p.action)}</span></td>
      <td>${esc(p.shot_at_risk) || '<span class="dim">—</span>'}</td>
      <td class="reason">${esc(p.reason)}</td>
      <td><span class="pill ${esc(p.decision)}">${esc(p.decision)}</span>
          ${p.decided_by ? `<span class="dim">by ${esc(p.decided_by)}</span>` : ""}</td>
      <td class="decide">
        ${pending ? `
          <button class="approve" data-job="${esc(p.job_id)}" data-action="${esc(p.action)}" data-decision="approved">Approve</button>
          <button class="reject" data-job="${esc(p.job_id)}" data-action="${esc(p.action)}" data-decision="rejected">Reject</button>`
        : `<span class="dim">recorded</span>`}
      </td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" class="empty">No proposals yet. Run the supervisor.</td></tr>`;
}

function renderQueryLog(data) {
  if (!data) return;
  $("query-log-badge").textContent = data.ok ? "live cluster" : "unavailable";
  $("query-log-note").textContent = data.note || "";
  $("query-log").innerHTML = (data.rows || []).map((r) => `
    <tr>
      <td>${shortTime(r.event_time)}</td>
      <td>${esc(r.user)}</td>
      <td>${compact(r.read_rows)}</td>
      <td>${nf.format(r.duration_ms)}</td>
      <td class="mono small">${esc(String(r.query).slice(0, 130))}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="empty">No recent rows.</td></tr>`;
}

// ------------------------------------------------------------------ timeline

const ROLE_COPY = {
  detect: "Detect",
  decide: "Decide",
  remediate: "Dry-run",
};

function timelineItem(s, passes) {
  return `
    <li class="timeline-step ${esc(s.agent)}">
      <div class="step-head">
        <span class="step-role">${esc(ROLE_COPY[s.role] || s.role)}</span>
        <span class="step-agent">${esc(s.label)}</span>
        ${s.pass ? `<span class="step-pass">pass ${s.pass} of ${passes || s.pass}</span>` : ""}
      </div>
      <div class="step-text">${mdLite(s.text)}</div>
      ${s.job_ids && s.job_ids.length
        ? `<p class="step-jobs">${s.job_ids.map((j) => `<code>${esc(j)}</code>`).join(" ")}</p>`
        : ""}
    </li>`;
}

function renderTimeline(steps, passes) {
  if (!steps || !steps.length) return;
  $("timeline").innerHTML = steps.map((s) => timelineItem(s, passes)).join("");
}

function appendTimelineStep(s, passes) {
  const list = $("timeline");
  if (list.querySelector(".timeline-empty")) list.innerHTML = "";
  list.insertAdjacentHTML("beforeend", timelineItem(s, passes));
}

function mcpItem(c, open) {
  const preview = (c.query || "").replace(/\s+/g, " ").trim();
  return `
    <li>
      <details ${open ? "open" : ""}>
        <summary>
          <span class="mcp-agent">${esc(c.label)}</span>
          <span class="mcp-preview">${esc(preview.slice(0, 110))}${preview.length > 110 ? "…" : ""}</span>
          <span class="mcp-tool">${esc(c.mcp_server)} · ${esc(c.tool)}</span>
        </summary>
        <pre><code>${esc(c.query)}</code></pre>
      </details>
    </li>`;
}

function renderMcp(calls) {
  const list = $("mcp-calls");
  state.mcpCalls = calls || [];
  if (!calls || !calls.length) {
    $("mcp-note").textContent =
      "This run made no MCP calls. That happens when the farm is clean and the Sentinel exits on its first pass.";
    list.innerHTML = "";
    return;
  }
  $("mcp-note").innerHTML =
    `${calls.length} <code>run_query</code> call${calls.length === 1 ? "" : "s"} through the official ` +
    `<code>mcp-clickhouse</code> server. The Sentinel composed this SQL from the schema; none of it is hardcoded in the repo.`;
  // Fourteen full SQL blocks is three thousand pixels of page. Collapse them:
  // the one-line preview is enough to see the agent is composing real queries,
  // and anyone who wants the whole statement is one click away.
  list.innerHTML = calls.map((c, i) => mcpItem(c, i < 2)).join("");
}

function appendMcp(call) {
  state.mcpCalls.push(call);
  const n = state.mcpCalls.length;
  $("mcp-note").innerHTML =
    `${n} <code>run_query</code> call${n === 1 ? "" : "s"} through the official ` +
    `<code>mcp-clickhouse</code> server. The Sentinel composed this SQL from the schema; none of it is hardcoded in the repo.`;
  $("mcp-calls").insertAdjacentHTML("beforeend", mcpItem(call, n <= 2));
}

function renderCost(cost, engine, fallback) {
  const el = $("cost-meter");
  if (!cost || !cost.model_calls) { el.hidden = true; return; }
  const which = engine || state.engine;
  const where = which === "agent_engine" ? "Vertex Agent Engine" : "in-process ADK";
  el.hidden = false;
  el.innerHTML =
    `This run: <strong>$${cost.usd.toFixed(4)}</strong> of ${esc(cost.model || "gemini-2.5-flash")} ` +
    `(${compact(cost.input_tokens)} in / ${compact(cost.output_tokens)} out, ` +
    `${cost.model_calls} calls, ${cost.elapsed_s}s) on ${where}.` +
    (fallback ? ` <span class="dim">${esc(fallback)}</span>` : "");
}

// ----------------------------------------------------------------- live feed

// ?nolive suppresses the stream. An open EventSource means the page never
// reaches a settled state, which hangs headless capture for screenshots.
function connectLive() {
  const pill = $("live-pill");
  const label = $("live-label");
  if (new URLSearchParams(location.search).has("nolive")) {
    pill.dataset.state = "off";
    label.textContent = "live feed paused";
    return;
  }
  let source;
  try {
    source = new EventSource("/api/stream");
  } catch {
    pill.dataset.state = "off";
    label.textContent = "live feed unavailable";
    return;
  }

  source.onmessage = (event) => {
    let snap;
    try { snap = JSON.parse(event.data); } catch { return; }
    pill.dataset.state = "live";
    label.innerHTML =
      `<strong>${nf.format(snap.running || 0)}</strong> jobs rendering · ` +
      `<strong>${nf.format(snap.hosts_active || 0)}</strong> hosts · ` +
      `${compact(snap.samples)} samples · ` +
      `<strong>${money(snap.open_waste_usd)}</strong> burning`;
    renderScale({ ...(state.scale || {}), samples: snap.samples, jobs: snap.jobs });
  };

  source.onerror = () => {
    pill.dataset.state = "off";
    label.textContent = "live feed reconnecting";
  };
}

// -------------------------------------------------------------------- actions

async function decide(button) {
  const body = {
    job_id: button.dataset.job,
    action: button.dataset.action,
    decision: button.dataset.decision,
    decided_by: "judge",
  };
  button.disabled = true;
  button.textContent = "…";
  try {
    const response = await fetch("/api/proposals/decide", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) throw new Error(await response.text());
    const data = await response.json();
    renderImpact(data.impact);
    renderProposals(data.proposals);
    const shots = await getJSON("/api/shots");
    renderShots(shots);
  } catch (err) {
    button.disabled = false;
    button.textContent = body.decision === "approved" ? "Approve" : "Reject";
    $("status").textContent = `Decision failed: ${err.message}`;
  }
}

function setStepper(role, pass) {
  const stepper = $("run-stepper");
  $("nav-run").hidden = false;
  const order = ["detect", "decide", "remediate"];
  const idx = order.indexOf(role);
  stepper.querySelectorAll("li").forEach((li) => {
    const r = li.dataset.role;
    li.classList.toggle("active", r === role);
    li.classList.toggle("done", idx >= 0 && order.indexOf(r) < idx);
    if (r === "detect" && pass) {
      li.textContent = `Detect · pass ${pass}`;
    } else if (r === "detect") {
      li.textContent = "Detect";
    }
  });
}

function startElapsed() {
  stopElapsed();
  state.runStarted = Date.now();
  const el = $("run-elapsed");
  el.textContent = "0s";
  state.tick = setInterval(() => {
    el.textContent = `${Math.round((Date.now() - state.runStarted) / 1000)}s`;
  }, 250);
}

function stopElapsed() {
  if (state.tick) {
    clearInterval(state.tick);
    state.tick = null;
  }
}

function applyComplete(data) {
  state.highlighted = new Set((data.highlighted_job_ids || []).map((j) => j.toLowerCase()));
  state.sentinelPasses = data.sentinel_passes || 0;
  renderTimeline(data.timeline, data.sentinel_passes);
  renderMcp(data.mcp_calls);
  renderCost(data.cost, data.engine, data.engine_fallback_reason);
  renderImpact(data.impact);
  renderWaste(data.waste);
  renderShots(data.shots);
  renderRootCause(data.root_cause);
  renderRollup(data.rollup);
  renderJobs(data.jobs);
  renderProposals(data.proposals);
  renderQueryLog(data.query_log);
  const pending = (data.proposals || []).filter((p) => p.decision === "pending").length;
  $("status").textContent =
    `Run ${data.run_id} complete. ${(data.mcp_calls || []).length} MCP queries, ` +
    `${pending} proposals awaiting approval.`;
  setStepper("remediate");
  $("proposals-section").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function applyFrame(frame) {
  switch (frame.type) {
    case "engine": {
      state.engine = frame.engine;
      const where = frame.engine === "agent_engine" ? "Vertex Agent Engine" : "in-process ADK";
      $("status").textContent = `Running on ${where}…`;
      break;
    }
    case "stage": {
      if (frame.pass) state.sentinelPasses = Math.max(state.sentinelPasses, frame.pass);
      setStepper(frame.role, frame.pass);
      const pass = frame.pass ? ` · pass ${frame.pass}` : "";
      $("status").textContent = `${frame.label}${pass} is working…`;
      break;
    }
    case "query":
      appendMcp(frame);
      $("status").textContent = `${frame.label} wrote a query (${state.mcpCalls.length} so far)`;
      break;
    case "step":
      if (frame.job_ids) {
        for (const job of frame.job_ids) state.highlighted.add(String(job).toLowerCase());
      }
      appendTimelineStep(frame, state.sentinelPasses || frame.pass);
      $("status").textContent = `${frame.label} reported.`;
      break;
    case "cost":
      renderCost(frame, state.engine, "");
      break;
    case "complete":
      applyComplete(frame);
      break;
    case "error":
      throw new Error(frame.message || "Supervisor run failed");
    default:
      break;
  }
}

async function consumeRunStream(response) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop();
    for (const part of parts) {
      const line = part.split("\n").find((l) => l.startsWith("data: "));
      if (!line) continue;
      applyFrame(JSON.parse(line.slice(6)));
    }
  }
  if (buffer.trim()) {
    const line = buffer.split("\n").find((l) => l.startsWith("data: "));
    if (line) applyFrame(JSON.parse(line.slice(6)));
  }
}

async function runSupervisor() {
  if (state.running) return;
  state.running = true;
  const button = $("run");
  button.disabled = true;
  state.mcpCalls = [];
  state.sentinelPasses = 0;
  state.engine = null;
  $("timeline").innerHTML = "";
  $("mcp-calls").innerHTML = "";
  $("mcp-note").textContent = "The Sentinel is composing SQL now.";
  setStepper("detect");
  $("status").textContent =
    "Detecting… the Sentinel is writing its own SQL against a quarter-billion telemetry rows.";
  startElapsed();
  $("agents").scrollIntoView({ behavior: "smooth", block: "start" });

  const headers = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  const token = $("token").value.trim();
  if (token) headers["X-Run-Token"] = token;

  try {
    const response = await fetch("/api/run", { method: "POST", headers, body: "{}" });
    if (response.status === 401) {
      $("token-row").hidden = false;
      throw new Error("A demo token is required for this deployment.");
    }
    if (response.status === 429) throw new Error("Run limit reached. Try again within the hour.");
    if (!response.ok) throw new Error(await response.text());

    const ctype = response.headers.get("content-type") || "";
    if (ctype.includes("text/event-stream") && response.body) {
      await consumeRunStream(response);
    } else {
      applyComplete(await response.json());
    }
  } catch (err) {
    $("status").textContent = err.message;
  } finally {
    stopElapsed();
    state.running = false;
    button.disabled = false;
  }
}

// ----------------------------------------------------------------------- boot

async function load() {
  const panels = [
    ["/api/scale", (d) => { state.scale = d; renderScale(d); }],
    ["/api/shots", renderShots],
    ["/api/impact", renderImpact],
    ["/api/waste", renderWaste],
    ["/api/root-cause", renderRootCause],
    ["/api/rollup", renderRollup],
    ["/api/jobs", (d) => renderJobs(d.jobs)],
    ["/api/proposals", (d) => renderProposals(d.proposals)],
    ["/api/query-log", renderQueryLog],
  ];
  await Promise.all(panels.map(async ([url, render]) => {
    try { render(await getJSON(url)); }
    catch (err) { console.warn(url, err); }
  }));

  // Replay the last run so the agent evidence is visible without spending one.
  try {
    const last = await getJSON("/api/last-run");
    if (last.available) {
      state.highlighted = new Set((last.highlighted_job_ids || []).map((j) => j.toLowerCase()));
      renderTimeline(last.timeline, last.sentinel_passes);
      renderMcp(last.mcp_calls);
      renderCost(last.cost, last.engine, last.engine_fallback_reason);
      $("status").textContent =
        `Showing run ${last.run_id}. Run the supervisor for a fresh audit.`;
    }
  } catch { /* no previous run on this instance */ }

  try {
    const health = await getJSON("/api/health");
    if (!health.run_public) $("token-row").hidden = false;
    if (!health.run_enabled) {
      $("run").disabled = true;
      $("status").textContent = "Supervisor runs are paused on this deployment.";
    }
  } catch { /* health is advisory */ }

  // Every panel fills in asynchronously, so the browser's own #anchor handling
  // fires against a page that is still a few hundred pixels tall and lands
  // nowhere. Re-apply the target once the content exists.
  const target = new URLSearchParams(location.search).get("at") || location.hash.slice(1);
  if (target && $(target)) $(target).scrollIntoView({ block: "start" });
}

// ?solo=<section-id> renders one section on its own. Headless capture ignores
// scroll position, so the alternative is cropping a tall screenshot at
// hardcoded offsets that break whenever the content length changes.
//
// Runs synchronously rather than at the end of load(): a screenshot can fire
// after the panels paint but before the last awaited fetch resolves, and then
// the whole page is still visible.
function applySolo() {
  const solo = new URLSearchParams(location.search).get("solo");
  if (!solo || !$(solo)) return;
  document.querySelectorAll("body > section, body > header, body > footer, body > nav, body > .back-top")
    .forEach((el) => { if (el !== $(solo)) el.hidden = true; });
}

function initNav() {
  const links = [...document.querySelectorAll(".nav-links a")];
  if (!links.length) return;
  const sections = links
    .map((a) => $(a.getAttribute("href").slice(1)))
    .filter(Boolean);
  const observer = new IntersectionObserver((entries) => {
    const visible = entries
      .filter((e) => e.isIntersecting)
      .sort((a, b) => b.intersectionRatio - a.intersectionRatio)[0];
    if (!visible) return;
    links.forEach((l) => {
      l.classList.toggle("active", l.getAttribute("href") === `#${visible.target.id}`);
    });
  }, { rootMargin: "-30% 0px -55% 0px", threshold: [0, 0.2, 0.5, 1] });
  sections.forEach((s) => observer.observe(s));
}

function initBackTop() {
  const btn = $("back-top");
  if (!btn) return;
  const onScroll = () => { btn.hidden = window.scrollY < 400; };
  window.addEventListener("scroll", onScroll, { passive: true });
  btn.addEventListener("click", () => window.scrollTo({ top: 0, behavior: "smooth" }));
  onScroll();
}

document.addEventListener("click", (event) => {
  const button = event.target.closest("button.approve, button.reject");
  if (button) decide(button);
});

$("run").addEventListener("click", runSupervisor);
$("recall-form").addEventListener("submit", runRecall);

applySolo();
initNav();
initBackTop();
load();
connectLive();
runRecall();
