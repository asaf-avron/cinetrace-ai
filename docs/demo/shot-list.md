# 3-minute demo — shot list

Re-record on the **same Vimeo id** (`https://vimeo.com/1220287055`) so the
Devpost embed does not need editing.

The rules ask for footage of the project functioning, not a cinematic trailer.
Screen capture with voiceover. No slides, no title cards beyond a few seconds.

## Before recording

1. Wake ClickHouse Cloud and confirm `/api/health` shows `clickhouse: true` and
   `live.ticks` increasing.
2. `uv run python -m cinetrace.clickhouse.reset_proposals` so the Impact card
   starts unrecovered and the Approve beat has somewhere to go. Do this between
   takes as well, not just once: proposals accumulate, and three rehearsal runs
   leave the same job in the table two or three times over, each protecting a
   different shot as the board moves.
3. Load the page and click **Run supervisor**. The run now streams: a sticky
   run bar docks under the nav with Detect → Decide → Dry-run, the elapsed
   timer, and the live status. Each SQL statement appears as the Sentinel
   writes it. Hold on the bar and the MCP list. Allow 90 to 100 seconds. After
   it finishes the bar hides; reload once so `/api/last-run` keeps the evidence
   on screen.
4. Browser at 1600px wide, dark OS theme, no bookmarks bar, no extensions.
5. Check "Dailies at risk" shows a handful, not zero and not forty.

**Do this run last.** The agent timeline and the MCP list are held in memory on
the instance, not in ClickHouse, so any deploy wipes them and the evidence
panels go blank until someone runs the supervisor again. A push touching
`src/**`, the Dockerfile or `pyproject.toml` redeploys; docs-only pushes do not.
Land your code first, then run, then record.

## The cut

**0:00–0:20 — The problem, stated as delivery**

Open on the hero. Read the headline off the screen — the count climbs as a
review approaches, so use whatever is live at record time. At time of writing:
seven shots will miss their review, five of them recoverable by freeing slots,
forty-two GPU slots held by zombie and idle-queue jobs.

Say "recoverable" only of the second number. Some shots are too far behind for
freed capacity to save them, and the panel says so per shot — claiming all of
them are recoverable is the one thing on this screen a judge can disprove.

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

Scroll to Root cause. The top row is `job-fail-oom`, NEBULA sh0040 on rnd-b04 at
97% VRAM — it sorts first reliably, so you can rehearse against it. Open the SQL
drawer. Read the gap off the screen rather than the script: the sample grid moves
when the farm is regenerated, so it lands somewhere in the low seconds.

> "When it finds an out-of-memory failure it runs an ASOF join — the last
> telemetry sample before the job died. This one died five seconds after the host
> hit 97% VRAM. Two million rows touched out of a quarter of a billion, and the
> panel tells you exactly what it cost. Almost nothing else lets you ask a
> database for the row just before a moment in a single join — anywhere else
> that's a window function or a correlated subquery."

**1:30–1:50 — Institutional memory**

Scroll to the recall panel. Type something conversational that shares no
keywords with the archive: **"we ran out of graphics memory halfway through"**.
It returns three OOM tickets against stored text reading "Allocation of 61523
MiB failed", which is the point — not one word in common.

Do not use "the card filled up and the job stopped". It now ranks an Arnold
licence ticket first, and the voiceover is about memory.

> "Error text is embedded with Vertex AI and searched by cosine distance in
> ClickHouse. It matches meaning, not keywords — so it finds the ticket from
> March and the fix that closed it."

**1:50–2:20 — The decision, tied to a deadline**

Back to the Orchestrator step in the timeline, then down to Proposals. A blank
PROTECTS cell is not a gap — it means that job was not blocking a delivery, and
the claim was dropped rather than invented. Say so if one is on screen; it is a
better beat than a full column.

> "The Orchestrator weighs findings against the dailies schedule. A zombie on a
> show with a review in five hours beats a bigger overrun due tomorrow. And when
> a proposal claims it protects a shot, that claim is checked against the
> delivery board before the row is written — a shot that's actually on track
> gets the claim dropped, not recorded. The agent doesn't get to mark its own
> homework."

**2:20–2:45 — Approval is the product**

Click **Approve** on a proposal. Cut to the Impact card moving.

> "Nothing has touched a render host. A proposal is a record, and the number
> only moves when a human approves it — because an agent finding waste doesn't
> reduce your bill. A supervisor approving the fix does."

**2:45–3:00 — Close**

Back to the top. Cost meter visible. Read the cents off the meter. Observed runs
land between two and four cents; it moves with how many passes the Sentinel
takes, and the call count moves with it.

> "Gemini, Google Cloud ADK, ClickHouse through MCP. This run cost about four
> cents and found six thousand dollars of capacity that's burning right now —
> and the reviews it was about to cost."

## Do not film

- The Agent Engine `:query` URL or any console with project internals
- The `.env` file, Secret Manager, or the demo token field
- A cold page — the first load after a redeploy shows empty panels
- The `?nolive` debug parameter

## Replacing the video on Vimeo

Replace the file in place rather than uploading a new video. The URL, the embed
code and the view count all survive, so **Devpost needs no edit at all** — the
id stays `1220287055`.

1. Open the video in your Vimeo library.
2. Hit **Replace** next to the Share button, or Settings → **Video file** →
   *Replace this video*. In the newer UI it is the version-history dropdown →
   **+ New version**.
3. Upload the new cut. The old one moves into version history, so you can
   restore it if the recut turns out worse.

Two things do not carry over:

- **Captions.** The old track stays attached and will be mistimed against the
  new cut. Delete it and upload `cinetrace-ai-demo.srt` fresh.
- **The thumbnail.** Reselect a frame, or you will ship a poster frame from the
  old cut.

## Accessibility

Upload English subtitles. `cinetrace-ai-demo.srt` in this folder is written
against the voiceover above; if you ad-lib away from the script, retime it.
