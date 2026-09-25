# MtaaniWatch Development Plan

## Goal

Build a focused, reliable demo of the complete report-to-resolution loop for drainage obstruction and flood-risk reports in Mombasa. A resident reports an issue, confirms the interpreted details, a coordinator assigns and tracks field work, and the resident receives a status update.

## Phase 1 — Confirm the demo setup

- Use **FastAPI** for the backend and the installed **PostgreSQL** instance for persistence.
- Start with **Africa's Talking SMS and Voice sandbox** for the reporting conversation. SMS supports text descriptions; Voice records a short spoken report, transcribes it, then uses SMS for resident confirmation and follow-up.
- Use the existing tunnel at `https://admin.mikesplore.me` pointing to FastAPI on port `8000` for Africa's Talking callbacks. Confirm the public URL is HTTPS and reachable before configuring the sandbox callback.
- Configure PostgreSQL with `DATABASE_URL` set to the supplied local database URL (`postgresql://mike@localhost:5432/mtaaniwatchdb`); keep the setting in a local environment file and out of committed secrets.
- Define seeded demo areas, drainage and flood-risk reports, and mock crews.
- Keep Africa's Talking and Groq credentials in environment variables.

**Deliverable:** FastAPI on port `8000` connects to PostgreSQL, the SMS sandbox can reach the tunneled webhook, and demo data is prepared.

## Phase 2 — Create the report and task foundation

- Model reports, possible clusters, tasks, assignments, and status history.
- Use PostgreSQL as the source of truth for reports, tasks, and status changes.
- Store only details supported by the resident's report; mark demo and unverified records clearly. Intake scope covers blocked or silted drainage channels, flooding/standing water, and objects or structures obstructing water flow. Unrelated complaints remain out of scope.
- Seed realistic reports and mock locations and crews.
- Implement backend operations to create and retrieve reports and update task status.

**Deliverable:** Reports can be stored and retrieved, and tasks can progress through `Reported → Assigned → In progress → Resolved`.

## Phase 3 — Build resident intake and confirmation

- Implement the SMS intake flow as a FastAPI webhook.
- Add an English/Kiswahili Voice IVR that records short reports and hands multilingual transcription into the same SMS confirmation flow.
- Use Groq to extract the incident type, area or landmark, stated impact, language, and concise summary.
- Validate the structured response and provide a readable fallback when AI is unavailable or returns invalid data.
- Ask the resident to confirm or correct the interpreted issue and location.
- Return a report reference and acknowledgment.

**Deliverable:** A resident-submitted report reaches the backend with confirmed details and a reference, including when AI is unavailable.

## Phase 4 — Deliver coordinator and crew workflows

- Build a simple responsive coordinator dashboard with incoming reports, area, severity cues, and status.
- Allow coordinators to review reports and manually assign tasks to mock crews.
- Allow task status progression and show the status history.
- Add a simple crew task view if time allows.

**Deliverable:** A coordinator can review a report, assign field work, and close the task.

**Implementation status:** Coordinator dashboard is available at `/dashboard`. It lists reports with area, impact, verification/demo labels, crew assignment, task status actions, status history, filters, summary counts, and automatic refresh. A separate crew view remains optional.

## Phase 5 — Suggest possible incident clusters

- Group reports with the same category in the same or nearby demo area.
- Present groups as possible clusters that need coordinator review.
- Allow a coordinator to accept or dismiss a suggestion.

**Deliverable:** Coordinators can review suggested groupings without treating them as proof of a verified incident.

**Implementation status:** The dashboard can generate, accept, and dismiss persisted suggestions. The first pass groups active reports with the same category and exact area; nearby-area matching can be added when trusted adjacency data is available. Kongowea is seeded as its own area and has been added to the local database.

## Phase 6 — Complete notifications and demo hardening

- Send an acknowledgment and resolution update through the selected channel when available.
- Keep a visible simulated notification mode for sandbox failures.
- Ensure sample data, locations, crews, and unverified reports are labeled in the interface.
- Rehearse the prepared Swahili/English report and prepare a backup seeded dataset.

**Deliverable:** The complete demo can be shown end to end even when an external service is unavailable.

**Implementation status:** Resident confirmation and resolution messages use the report language. The originating SMS `linkId` is retained for later premium replies. Task history and the dashboard show whether SMS was accepted by Africa's Talking or simulated after missing credentials, recipient, or provider failure. Seeded data remains visibly labeled, and [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) contains the Swahili/English rehearsal and seeded-data recovery steps. Sandbox API acceptance does not verify handset delivery; confirm that separately through a delivery report or resident-side check.

## Two-day sequencing

### Day 1 — Make the core loop work

Complete Phases 1–4 in order. Prioritize a vertical slice from report intake through confirmation, dashboard review, assignment, and status progression.

### Day 2 — Connect, polish, and rehearse

Complete Phases 5–6. Polish visible workflow states and rehearse the complete story. If time is constrained, keep the report-to-resolution loop and defer clustering or the crew view.

## Demo acceptance criteria

- A report reaches the dashboard from the resident channel without manual database editing.
- AI output is structured, validated, and correctable by the resident or coordinator.
- A coordinator can assign a task and mark it resolved.
- The resident acknowledgment and resolution update are shown or sent.
- Demo data and unverified reports are clearly labeled.
- The demo remains understandable and complete if an external API is unavailable.

## Explicitly deferred

- Crew-to-crew chat and automated dispatch.
- AI decisions about report truth, danger, or safe actions.
- Claims of live county, emergency-service, weather, or network integration.
- Multiple incident categories, advanced GIS, real-time flood prediction, and live voice transcription.
