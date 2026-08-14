# CineTrace AI

Autonomous multi-agent VFX studio supervisor for Media & Entertainment. CineTrace AI eliminates render-farm compute waste by analyzing farm telemetry.

Built for [Agentic Cinema: The Blockbuster Hackathon](https://agentic-cinema.devpost.com/) on the **ClickHouse** partner track.

## Mission

Our mission is to develop and orchestrate CineTrace AI, an autonomous multi-agent system designed for the Media & Entertainment industry. CineTrace AI will act as a VFX studio supervisor to eliminate compute waste by analyzing render farm telemetry. As the orchestrator, your role is to assist in building, testing, and managing our three core sub-agents—the Diagnostic Sentinel, the Studio Orchestrator, and the Action Agent—and ensuring they properly connect to ClickHouse via the Model Context Protocol (MCP).

## Agents

| Agent | Role |
| --- | --- |
| **Diagnostic Sentinel** | Detect waste and anomalies in render-farm telemetry |
| **Studio Orchestrator** | Decide what to do next |
| **Action Agent** | Execute the remediation |

All three connect to **ClickHouse via MCP**. ClickHouse is the telemetry store; queries must be real, not mocked.

## Stack

- **Gemini** + **Google Cloud Agent Builder / Agent Engine (ADK)** as the submission core
- **ClickHouse** via **MCP** for telemetry
- Google Cloud and ClickHouse must be imported and called in code, not only named here

Hackathon resources: [agentic-cinema.devpost.com/resources](https://agentic-cinema.devpost.com/resources)

## Submission (Devpost)

Deadline: **Sep 9, 2026 @ 2:00pm PDT**. Judging: implementation, design, impact, idea quality. ClickHouse track prizes: $7,500 / $4,500 / $3,000.

Before submit:

- [ ] Flip this repo from private to **public**
- [ ] Add a complete open-source license (visible in GitHub About)
- [ ] Prove Google Cloud and ClickHouse are used at runtime in code
- [ ] Hosted project URL
- [ ] 3-minute **working demo** video (YouTube/Vimeo, English or English subtitles)
- [ ] Complete the Devpost form and select the ClickHouse track
