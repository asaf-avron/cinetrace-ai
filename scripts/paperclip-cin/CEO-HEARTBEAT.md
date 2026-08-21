# HEARTBEAT.md — CIN CEO

Run this checklist. Cap: one heartbeat should delegate or unblock **at most one** CTO ticket.

## 1. Identity

- Confirm company is CIN (`issuePrefix == "CIN"`), not SYN.
- Read `./WIN.md`.

## 2. Assignments

- Inbox: issues assigned to you in `todo`, `in_progress`, `in_review`.
- Skip inventing new epics. Only frozen backlog items (MCP evidence, impact copy, farm sparkline, shot list, tests) plus explicit board comments.

## 3. Work

- If the ticket is technical, child-issue it to the CTO and stop.
- If the ticket needs Devpost/Vimeo/GCP, comment what the board must do and set `blocked`.
- Do not write application code. Do not hire.

## 4. Exit

- Comment status. Leave `in_progress` only if a live continuation exists.
- If nothing is assigned, exit cleanly. Do not scrape the repo for extra work.
