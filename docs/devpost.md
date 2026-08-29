# Devpost submission copy

Paste-ready. The current live page has only "What it does" and "How we built
it", which leaves points on the table and misses a stated rule: the official
rules require the text description to include *"your findings and learnings as
you worked through the project."*

---

## Inspiration

A VFX render farm is the most expensive machine in a studio and nobody watches
it in real time. Everybody watches the schedule instead.

That gap is where the idea came from. Talk to anyone who has run a farm and they
do not describe compute waste as a cost problem — they describe the morning a
sequence missed dailies because a job had been "running" since Tuesday on eight
GPUs and nobody noticed. The money is real, but the thing that gets someone
shouted at is the empty slot in the review session.

Most FinOps dashboards would show that job as a line item in a monthly report.
We wanted the opposite: a supervisor that notices at 2am, works out *why*, and
says which shots it is about to cost you.

## What it does

CineTrace AI watches a render farm's telemetry in ClickHouse and turns wasted
compute into a delivery forecast.

The headline is not dollars, it is **"7 shots will miss review, 5 are
recoverable"** — a count that moves with the farm, climbing as a review
approaches and resetting when the session rolls. The two numbers rarely match,
which is the point: some shots are already too far behind for freed capacity to
save.

Both come out of a single SQL projection rather than a rule of thumb. It walks
each show's shot queue in review order, accumulating the frames still owed ahead
of every shot with a window function, then divides by the slots that show is
actually running to get an ETA. The per-frame rate is not a constant — it is the
median hours-per-frame for that show and renderer, read from a
`quantileTDigest` baseline over completed jobs, so a slow renderer is not
mistaken for a late shot. A shot is at risk when its ETA runs past its review
time. It is *recoverable* when the same arithmetic, re-run with the zombie and
idle-queue slots handed back, brings it inside the deadline. That difference is
the entire product thesis, expressed as a column.

Underneath it, three Gemini agents on Google Cloud ADK run a fixed
detect → decide → act pipeline:

- The **Diagnostic Sentinel** is given the schema and a goal, not a list of
  queries. It composes its own SQL through the official `mcp-clickhouse` server
  — 5 to 16 `run_query` calls per run, depending on how many passes it decides
  to take — starting broad and drilling into whatever looks worst. When it finds
  an OOM failure it runs an `ASOF LEFT JOIN` against a quarter-billion telemetry
  samples to find the last reading before the job died, and reports things like
  *"job-live-900409 died 4 seconds after host rnd-e20 hit 97% VRAM."*
- The **Studio Orchestrator** weighs those findings against the dailies
  schedule. Waste that threatens a client review outranks waste that only costs
  money, so a zombie on a show with a review in five hours beats a bigger
  overrun on a show with a review tomorrow.
- The **Action Agent** records dry-run remediations with the evidence and, when
  the job is blocking a delivery, the shot it protects. That last claim is the
  strongest thing the product says, so it is the one claim the model does not
  get to assert unchecked: the shot is verified against the live delivery board
  before the row is written, and a shot that is comfortably on track gets the
  claim dropped rather than recorded.

Nothing reaches a render host. Each proposal arrives as a row in the supervisor
UI carrying the evidence it was built from — the job, the action, the shot it
protects, and the Sentinel's own reasoning — with Approve and Reject sitting
beside it. Approving credits that one job's waste to the Impact card and writes
an append-only decision record; rejecting is recorded just as permanently and
credits nothing. The dollar figure only moves on approval, because an agent
finding waste does not reduce your bill and a supervisor approving the fix does.

The farm is live while you watch it: a background ticker writes fresh telemetry
every 30 seconds and the page streams updates over SSE.

**Scale:** 244M frame samples, 198k render jobs, 240 hosts, three months of
history, 3.9 GB.
The ticker keeps writing, so the live page reads higher every day until the
100-day TTL parks it around a quarter of a billion rows.

## How we built it

**Google Cloud.** Gemini 2.5 Flash through the Agent Development Kit. The
pipeline is an ADK `SequentialAgent` wrapping the three agents, with the Sentinel
itself a `LoopAgent` so it can react to what it found rather than answering in
one shot. Stages hand off through session state. The pipeline runs in-process on
Cloud Run; the same `root_agent` can be pointed at Vertex AI Agent Engine by
setting `AGENT_ENGINE_ID`. Error text is
embedded with Vertex AI `text-embedding-005`. The supervisor UI is FastAPI on
Cloud Run; secrets are in Secret Manager; deploys run through GitHub Actions with
Workload Identity Federation so no GCP credentials exist outside Google.

**ClickHouse.** ClickHouse Cloud is the telemetry store, reached two ways on
purpose: agents get the official `mcp-clickhouse` stdio server, where `run_query`
is select-only, and the application writes over HTTPS with `clickhouse-connect`.
The read path an agent gets is deliberately narrower than the write path the app
holds.

The schema leans on things that are ClickHouse-specific rather than incidental:

- `frame_samples` is a `MergeTree` partitioned by day, ordered by `(job_id, ts)`,
  with a **projection** on `(host, ts)` so the ASOF root-cause join can seek by
  host, plus `set` and `minmax` skip indexes and a 100-day TTL.
- A **materialized view** aggregates into an `AggregatingMergeTree` on insert,
  so the dashboard reads about 900k pre-computed rows instead of a
  quarter-billion raw ones.
- **`quantileTDigest`** builds per-(show, renderer) baselines. The old rule was
  `cpu_hours >= 100`, which is meaningless across renderers whose costs differ
  by 10x; now a job is an overrun when it crosses a robust upper fence,
  `p50 + 3 × (p95 − p50)`, for its own cohort.
- **`lagInFrame`** finds hosts failing repeatedly inside 90 minutes.
- **`cosineDistance`** over `Array(Float32)` embeddings does semantic recall
  across the incident archive.
- The entire farm is generated inside the database with
  `INSERT ... SELECT ... FROM numbers_mt`, so no rows ever cross the wire.

**Data sources.** All telemetry is synthetic and generated by
`src/cinetrace/clickhouse/generate.py`. No real studio data was used, and none of
it is scraped or third-party. Randomness is `cityHash64`-seeded, so the farm
rebuilds identically and the numbers in the video match the numbers in the repo.

## Challenges we ran into

**The first version did not need ClickHouse.** It ran on 62 rows. Every query
would have produced identical output on SQLite, which is a strange thing to
submit to a ClickHouse track. Fixing that meant rebuilding the data model around
a frame-level fact table instead of a job-level one — hundreds of millions of
rows instead of 62 — and rewriting the impact calculation, which had been
summing in a Python loop over every job. That does not survive 198k rows.

**Scale exposes lazy SQL immediately.** The first ASOF join had no bound on its
right side, so ClickHouse tried to materialise the whole fact table and hit the
7.2 GiB memory ceiling. Bounding both sides — the failure window and the handful
of hosts actually involved — takes it to about 2M rows, and the page prints that
count on every load so you can check us. Similar story with alias shadowing:
`sum(waste_cpu_hours) AS waste_cpu_hours` is fine alone but
makes any other aggregate reading that column fail with "aggregate function
inside another aggregate function".

**Agents optimise exactly what you measure.** Our first working run had the
Sentinel confidently reporting three overruns and the Orchestrator concluding
"these actions are not intended to save any specific shots". It was right: the
biggest dollar figures *were* overruns. But overruns are completed jobs, so
there is nothing to reclaim. The bug was in the waste model, not the prompt — we
were marking completed jobs as actionable. Once `is_open` meant "an action can
still change this", the same agents immediately started picking zombies and
idle-queue jobs and tying them to specific reviews.

**A demo has to survive being left alone.** Judging runs two to four weeks after
the deadline. Every predicate the Sentinel uses is relative to `now()`, so a
static seed rots: leave it a week and every "running" job drifts past the
six-hour zombie threshold, and the farm reads as one enormous outage. The live
cohort now rebuilds itself against a fresh `now()` every 15 minutes.

**The ticker was too generous.** The first version advanced every shot by up to
two frames every 30 seconds, so the delivery board drained and "dailies at risk"
was permanently zero within the hour. Matching it to real farm throughput — 224
slots at ~0.46 hours per frame is about four frames per tick across all shows,
not two per shot — made it stable.

## Accomplishments that we're proud of

The Sentinel writing its own SQL. There is a panel on the page showing the exact
statements the model composed against a schema it was handed, including ASOF
joins it chose to use, and none of it is hardcoded in the repo. That is the
difference between an agent and a prompt with queries pasted in.

The root-cause line. *"This job died 4 seconds after the host hit 97% VRAM"* is
a sentence a render wrangler would write, produced by a single ASOF join that
reads about 2M rows out of a quarter-billion — the bounds and the `(host, ts)`
projection do that work, not a bigger cluster.

The honesty of the numbers. The page distinguishes waste you can still act on
from waste that already happened, refuses to credit a saving until a human
approves it, and shows the at-risk shots that freeing slots would *not* rescue.
Two guards enforce that in code rather than in prompt wording: a proposal
claiming it protects a shot has the claim dropped unless the live delivery board
agrees, and a job id that does not resolve to a real job is refused outright. It
would have been easy to make every number look recoverable.

And the detector is scored, not admired. Synthetic data usually costs you the
ability to tell a finding from a coincidence; here it buys the opposite, because
the generator seeds six jobs whose correct classification is known before the
farm is written. A test in CI asserts that the `job_waste` view recovers all six
in their own class — including that a completed overrun is real money but stays
out of the actionable total, since no action reclaims hours already spent.

And the supervisor reports its own cost. A tool that kills compute waste should
be able to say what it spends: two to four cents of Gemini per run.

## What we learned

**Partner-track projects live or die on whether the partner product is
load-bearing.** The useful question was not "are we calling ClickHouse?" but
"would this still work on Postgres?" Every honest answer of "yes" was a feature
we had not really built yet.

**Determinism and autonomy are not opposites.** Letting the model choose the
control flow via `sub_agents` transfer bought nothing and cost reliability. A
`SequentialAgent` guarantees the three stages while leaving the interesting
reasoning — which SQL to write, which job matters — entirely to the model.

**Statistical thresholds beat constants, and they are cheap.** Replacing
`cpu_hours >= 100` with a per-cohort tDigest fence took one view, made the
detector defensible, and removed an argument we could not win about what the
right constant was.

**Agent guardrails belong in the data model.** We tried to fix the overrun
fixation with prompt wording first. It half-worked. Fixing the definition of
"actionable" fixed it completely and permanently, for every future prompt.

**Watch what the model does with a quarter-billion-row table.** The Sentinel
bounds its `frame_samples` queries by job id and time range because the schema
brief tells it to, in the same paragraph that tells it how big the table is.
Without that, an agent will happily write the query that takes the cluster down.

## What's next for CineTrace AI

Closing the loop: real execution against OpenCue or Deadline, gated on the
approval record that already exists. The audit trail was built for this.

Real ingestion, replacing the generator with a live feed from farm schedulers,
which is mostly a matter of the Kafka table engine and keeping the same schema.

Learning from outcomes: every approved and rejected proposal is a labelled
example of whether the supervisor was right. Feeding rejections back would let
the Orchestrator's priorities adapt to a studio instead of shipping with ours.

Bidding on the schedule rather than only reporting it — if the farm knows which
reviews are at risk, the next step is proposing the reallocation, not just
freeing the slot.

---

## Gallery captions

Devpost currently has **zero screenshots**. Upload these with the captions
below; the thumbnail should be the first one.

Devpost caps a caption at **140 characters**, so keep one claim per image and
let the story section carry the detail.

| File | Caption |
| --- | --- |
| `01-dailies-at-risk.png` | Delivery, not cost: the shots that will miss review, and how many come back if the stuck GPU slots are freed. |
| `02-impact-and-waste.png` | Open waste is what an agent can still change; the full-history figure sizes the problem. Approval, not detection, moves the number. |
| `03-three-agents.png` | Detect → decide → dry-run as an ADK SequentialAgent, so no stage can be skipped. The Orchestrator names the review each fix protects. |
| `04-mcp-evidence.png` | SQL the Sentinel composed itself, through the official mcp-clickhouse server. None of these statements exist in the repo. |
| `05-root-cause-asof.png` | ASOF LEFT JOIN: the last sample before each OOM death, 2M rows out of a quarter-billion. VRAM at 97% is the smoking gun. |
| `06-semantic-recall.png` | Vertex AI embeddings, cosineDistance in ClickHouse. Describe a failure in plain language and the archive returns the fix that worked. |
| `07-detection-sql.png` | Every panel shows its own SQL, what it cost, and the true match count. Thresholds are per-cohort tDigest fences, not constants. |
| `08-proposals-approval.png` | Dry-run and append-only: nothing reaches a render host until a human approves. PROTECTS is verified against the live delivery board. |
| `09-full-page.png` | The whole supervisor. |

## Built With

`adk` · `clickhouse` · `cloud-run` · `fastapi` · `gemini` · `google-cloud`
`mcp-clickhouse` · `vertex-ai` · `materialized-views`
`vector-search` · `python`

## Try it out

- Live supervisor: https://cinetrace-781071502822.us-central1.run.app
- Source: https://github.com/asaf-avron/cinetrace-ai
