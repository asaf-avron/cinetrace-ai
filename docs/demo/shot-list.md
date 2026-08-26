# 3-minute demo — shot list

Re-record on the **same Vimeo id** (`https://vimeo.com/1220287055`) so the
Devpost embed does not need editing.

The rules ask for footage of the project functioning, not a cinematic trailer.
Screen capture with voiceover. No slides, no title cards beyond a few seconds.

## Before recording

1. Wake ClickHouse Cloud and confirm `/api/health` shows `clickhouse: true` and
   `live.ticks` increasing.
2. `uv run python -m cinetrace.clickhouse.reset_proposals` so the Impact card
   starts unrecovered and the Approve beat has somewhere to go.
3. Load the page and click **Run supervisor**. The run now streams: a sticky
   run bar docks under the nav with Detect → Decide → Dry-run, the elapsed
   timer, and the live status. Each SQL statement appears as the Sentinel
   writes it. Hold on the bar and the MCP list. After it finishes the bar
   hides; reload once so `/api/last-run` keeps the evidence on screen.
4. Browser at 1600px wide, dark OS theme, no bookmarks bar, no extensions.
5. Check "Dailies at risk" shows a handful, not zero and not forty.

## The cut

**0:00–0:20 — The problem, stated as delivery**

Open on the hero. Read the headline off the screen — the count climbs as a
review approaches, so use whatever is live at record time. At time of writing:
three shots will miss their review, all three recoverable, forty-two GPU slots
held by zombie and idle-queue jobs.

> "A render farm is the most expensive machine in a studio, and nobody watches
> it in real time. When a job hangs overnight on eight GPUs, the cost isn't the
> compute. It's the three shots that miss the 9am review."

**0:20–0:35 — The scale, briefly**

Pan across the scale strip. Point at the live pill counting up.

> "This is a quarter of a billion rows of frame-level telemetry in ClickHouse.
> 198,000 jobs, 240 hosts, and it's still being written to while we watch."

**0:35–1:05 — The agents, and the SQL they write live**

Stay on the three-agent panel while the run is in flight. The run bar under
the nav and the SQL list are the shot — do not cut away to a spinner.

> "Three Gemini agents on Google Cloud ADK. The Sentinel isn't given queries —
> it's given the schema and a goal, and it writes its own SQL through the
> official ClickHouse MCP server. You're watching it compose those against a
> quarter of a billion rows, live. None of them are in our repo."

**1:05–1:30 — Root cause. The best thirty seconds.**

Scroll to Root cause. Land on the 97% VRAM row. Open the SQL drawer.

> "When it finds an out-of-memory failure it runs an ASOF join — the last
> telemetry sample before the job died. This one died twenty seconds after the
> host hit 97% VRAM. Two point two million rows touched out of a quarter of a
> billion, and the panel tells you exactly what it cost. You cannot ask a
> database 'the row just before this moment' in one join anywhere else."

**1:30–1:50 — Institutional memory**

Scroll to the recall panel. Type something conversational that shares no
keywords with the archive, e.g. *"the card filled up and the job stopped"*.

> "Error text is embedded with Vertex AI and searched by cosine distance in
> ClickHouse. It matches meaning, not keywords — so it finds the ticket from
> March and the fix that closed it."

**1:50–2:20 — The decision, tied to a deadline**

Back to the Orchestrator step in the timeline, then down to Proposals.

> "The Orchestrator weighs findings against the dailies schedule. A zombie on a
> show with a review in five hours beats a bigger overrun due tomorrow. Every
> proposal names the shot it protects."

**2:20–2:45 — Approval is the product**

Click **Approve** on a proposal. Cut to the Impact card moving.

> "Nothing has touched a render host. A proposal is a record, and the number
> only moves when a human approves it — because an agent finding waste doesn't
> reduce your bill. A supervisor approving the fix does."

**2:45–3:00 — Close**

Back to the top. Cost meter visible.

> "Gemini, Google Cloud ADK, ClickHouse through MCP. This run cost about seven
> cents and found six thousand dollars of capacity that's burning right now —
> and the reviews it was about to cost."

## Do not film

- The Agent Engine `:query` URL or any console with project internals
- The `.env` file, Secret Manager, or the demo token field
- A cold page — the first load after a redeploy shows empty panels
- The `?nolive` debug parameter

## Accessibility

Upload English subtitles. The existing `.srt` in this folder is for the previous
cut and must be replaced, not reused.
