const jobsBody = document.getElementById("jobs");
const proposalsBody = document.getElementById("proposals");
const summary = document.getElementById("summary");
const status = document.getElementById("status");
const runBtn = document.getElementById("run");

function cell(text) {
  const td = document.createElement("td");
  td.textContent = text == null ? "" : String(text);
  return td;
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

async function refresh() {
  const [jobsRes, propRes] = await Promise.all([
    fetch("/api/jobs"),
    fetch("/api/proposals"),
  ]);
  if (!jobsRes.ok || !propRes.ok) {
    throw new Error("ClickHouse API failed. Check .env and that the service is awake.");
  }
  const jobs = await jobsRes.json();
  const proposals = await propRes.json();
  renderJobs(jobs.jobs);
  renderProposals(proposals.proposals);
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
