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
3. Optionally spend one run as a smoke test: click **Run supervisor** and watch
   a sticky bar dock under the nav with Detect → Decide → Dry-run, the elapsed
   timer, and each SQL statement appearing as the Sentinel writes it. Time it —
   runs land between 65 and 101 seconds and you want to know today's number
   before you roll. Then go back to step 2 and reset, because the take has its
   own run and you do not want this one's proposals still in the table.
4. Browser at 1600px wide, dark OS theme, no bookmarks bar, no extensions.
5. Check "Dailies at risk" shows a handful, not zero and not forty.
   **Do not roll while `#shots-recoverable` is 0.** The ticker swings
   (10/6, then 8/4, then 2/0). A hero that opens on a green zero under
   "recoverable by freeing stuck slots" argues against the product: the
   pitch is that freeing slots saves reviews. Read `/api/shots` (or the
   live DOM) once; keep the live number and do not hardcode a count.
   `scripts/demo/record_demo.py` refuses the take if the gate is closed.
   Do not sit in a multi-hour poll — NEBULA's session is hours, not
   minutes, and a 0/0 board after a roll is a designed trough. The
   board owns `--refresh-live` (never `--jobs-only`, never truncate
   `frame_samples`). After a re-seed, verify after a full ticker tick.

**Land your code before you roll.** The agent timeline and the MCP list are held
in memory on the instance, not in ClickHouse, so any deploy wipes them and the
evidence panels go blank until someone runs the supervisor again. A push touching
`src/**`, the Dockerfile or `pyproject.toml` redeploys; docs-only pushes do not.
No state you film survives a deploy, so finish the code first.

**Five runs an hour.** The supervisor allows five runs per rolling hour and
answers the sixth with a 429, on camera if that is where you are. Rehearsal runs
count against it. Budget the takes; if you burn the allowance, wait it out,
because the only other way to clear the counter is a redeploy and that wipes the
evidence panels. Approvals are capped far higher, at sixty an hour, so
re-recording the Approve beat costs nothing.

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

Click **Run supervisor** at the top of the take, over the hero read, not here.
Runs land between 65 and 101 seconds, so a click at 0:35 can still be streaming
when the Orchestrator beat is due at 1:50, while a click at 0:05 has SQL on
screen by 0:35 and is finished with room to spare. The first statements appear
within a few seconds of the click, so there is always something on screen to
hold on.

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

Click **Approve** on a proposal, then cut to the Impact card moving.

Pick the most expensive row — a zombie, not a retry loop. Only jobs that are
still open credit a saving, and the credit is that one job's own waste, so the
size of the jump is entirely your choice of row: in rehearsal a zombie moved
`remaining` by $104.85 and a retry loop by $15.42. This number moving is the
payoff of the whole video, so make it one the eye catches. A job that is already
approved will not move it twice, which is the other reason to reset between
takes.

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

## Automated capture

The beats above are written for a person with a screen recorder. The first cut
was not made that way — the CIN CTO agent produced it with a scripted Playwright
capture and a TTS narration track. The harness now lives at
`scripts/demo/record_demo.py` (system Python + Playwright; reset proposals with
the worktree `.venv`). So if an
agent is recording this again, the mechanics below replace the parts of the
script that assume a hand on a mouse.

Everything needed is already on the Oracle host: Playwright 1.59 for both node
and python, ffmpeg 6.1, espeak-ng, and ClickHouse credentials in
`/opt/cinetrace-ai/.env` so `reset_proposals` works. Work in a worktree off
current `main`, on a feature branch, and open a PR — never push `main`. Land no
code at all during the recording window: a push touching `src/**`, the Dockerfile
or `pyproject.toml` redeploys, and the redeploy wipes the in-memory run evidence
that half these beats are pointing at.

**Set the viewport, ignore the chrome.** Headless Chromium, viewport 1600×900,
`deviceScaleFactor: 2`, `colorScheme: "dark"`. The "no bookmarks bar, no
extensions" half of step 4 is a no-op headless. The width is not: the layout has
a breakpoint and a narrower viewport reflows the panels into a column.

**Refuse a 0-recoverable hero.** Confirm `/api/shots` `recoverable_count > 0`
once *before* opening the recorder, then confirm the DOM
(`#shots-recoverable`) is still greater than zero after load. If the
ticker flipped to zero between the API check and the first frame, abort
the take. Do not idle in a poll loop — post and stop; the board decides
whether to `--refresh-live`. `build_beats` still reads the live count;
the gate is what stops the degenerate 2/0 opening.

**Captions come from speech, not even slices.** Synthesize each sentence
(or clause) separately. Prefer edge-tts `--write-subtitles` for the
measured start/end of that clip; otherwise use the clip's
`ffprobe` duration. Never divide a beat's span by `len(sentences)`.
Split any cue over ~20 characters/sec across two cues.

**The hosted URL has to be drawn on.** Headless Chromium has no address
bar. Burn `https://cinetrace-781071502822.us-central1.run.app` as an
ffmpeg `drawtext` lower-third on the first few seconds of the cut so
judges can see it is the deployed farm.

**The narration is generated, not read aloud off the screen.** Four beats tell
you to read a live number rather than trust the script, which a pre-rendered TTS
track cannot do. Resolve them before synthesis by reading the rendered text of
the element itself, so the words and the frame cannot disagree:

| Beat | Read the text of | Instead of saying |
|---|---|---|
| 0:00 hero | `#shots-at-risk`, `#shots-recoverable`, `#slots-stuck` | seven, five, forty-two |
| 0:20 scale | `#scale-samples`, `#scale-jobs`, `#scale-hosts` | a quarter of a billion |
| 1:05 root cause | `#asof-stats`, first row of `#asof-rows` | five seconds, two million rows |
| 2:45 close | `#cost-meter`, `#impact-open` | four cents, six thousand dollars |

**Scroll to anchors rather than panning.** The nav holds the canonical positions
— `#top`, `#dailies`, `#impact-row`, `#agents`, `#root-cause`, `#recall`,
`#sentinel-queries`, `#farm-hours`, `#proposals-section` — so
`scrollIntoViewIfNeeded()` lands each beat where the sticky nav expects it.
"Point at the live pill" is a `hover()` on `#live-pill`. For the recall beat,
fill `#recall-input` and submit `#recall-form`; the field ships pre-filled with a
conversational OOM phrase, so overwrite it only if you want the exact wording
from the 1:30 beat.

**`networkidle` never fires on this page.** It holds an open `EventSource` on
`/api/stream` for the live ticker, so `wait_until="networkidle"` times out every
single time. Navigate with `wait_until="load"` and gate on a selector instead —
`#shots-at-risk` is a good first one. Two beats also depend on a completed run
rather than merely a loaded page: `#cost-meter` is blank until then, and
`button.approve` does not exist at all until a run has filed proposals. Capture
2:20 and 2:45 after the run finishes, not before.

**Wait on the run instead of timing it.** Click `#run` once at the top of the
capture. No credential is needed — `#token-row` is hidden because runs are
public. Then wait for completion rather than assuming the 0:35 mark: subscribe to
`/api/stream`, or poll `#run-status` until `#run-bar` hides. Runs land between 65
and 101 seconds. Take one continuous capture and cut the beats in post; the
timings under "The cut" are targets for the edit, not for the browser.

**Approve the row that moves the number, not the first one.** Join
`/api/proposals` to `/api/jobs` on `job_id`, keep the rows where `is_open` is
true, take the highest `waste_usd`, and click
`button.approve[data-job="<that job id>"]`. The credit is that one job's own
waste, so this choice is the difference between the Impact card jumping by $104
and by $15. `/api/jobs` is only the top 60 waste rows — if the run proposed a
job outside that list, fall back to any pending `button.approve` rather than
aborting. Do not treat a leftover `#cost-meter` from the previous run as
proof this take finished; wait for an Approve button that did not exist
after `reset_proposals`.

**Budget the runs.** Five per rolling hour normally, raised for the recording
window and put back afterwards; the overflow is a 429. Iterate the Playwright
script against a page that has already run rather than spending a supervisor run
on every attempt, and call `reset_proposals` between real takes.

**Deliverables, and where they stop.** An MP4 plus a retimed
`cinetrace-ai-demo.srt` if the narration drifts from the script. `docs/demo/*.mp4`
is gitignored, so the HQ file stays at that path in the worktree and a compressed
copy under ~1 MB goes to Paperclip as the issue artifact, the way CIN-7 handed
off the first cut. **The Vimeo replace below is human-only** — there is no Vimeo
credential on the host and there should not be one.

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
