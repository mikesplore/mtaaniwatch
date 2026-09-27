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

## Targeted fix plan — restore a clear coordinator workflow

The dashboard currently has reports without response tasks, and task/cluster behavior is not obvious to coordinators. Complete these phases in order; each phase should leave the app usable before the next begins.

### Phase A — Recover reports that have no task

- Keep task creation available from report details, without requiring the report to be verified first.
- Add a bulk recovery action for legacy reports with no task; create one `reported` task and initial history event per report, safely on repeat requests.
- Make the migration/backfill path explicit for existing deployments so the task count does not depend on whether a report was created through the newest intake code.
- Keep report verification as a separate review decision, not a prerequisite to starting response work.

**Checkpoint:** A report with no task can receive one from the UI; repeated clicks or retries do not create duplicate tasks. Existing taskless rows can be recovered in bulk and appear in the Tasks view.

**Implementation status:** The report details drawer can create a task without verification, and the Tasks page can backfill every taskless report. The per-report unique constraint plus conflict recovery makes repeated and concurrent creation requests safe. No schema migration is needed for this phase.

### Phase B — Make report triage understandable

**Implementation status:** The reports table now shows verification/disposition and response states separately; taskless reports remain visible under response status filters; report details explain the next coordinator action; and coordinators can record an auditable out-of-scope decision with a required reason. Coordinator task actions already create timestamped history; verification stays independent of response work.

- Show each report's review state and response state as separate fields in the report list and details view.
- Explain the next action for each state: verify/correct details, create or assign a task, or record why the report is out of scope.
- Ensure task status filters include taskless reports or label them clearly, so filtering does not make reports disappear.
- Keep task actions in timestamped task history; store report verification as its own review decision and out-of-scope decisions with reason, actor, and timestamp.

**Checkpoint:** A coordinator can tell whether a report is verified, has a task, and what action is available without opening unrelated screens. A report can be marked out of scope with a recorded reason, actor, and timestamp; this disposition remains separate from task cancellation.

### Phase C — Make cluster suggestions reflect reports

**Implementation status:** Cluster scans include taskless reports, exclude resolved/cancelled tasks and out-of-scope reports, refresh the current unreviewed suggestion for each category/area, and remove it when fewer than two eligible reports remain. Accepted and dismissed suggestions are retained as coordinator history; the same exact membership is not suggested again. Cards explain the exact-match rule and why the grouping was suggested.

- Discover clusters from reports with a known area and active status, even if a task has not yet been created. Exclude reports whose tasks are resolved or cancelled.
- Keep the current exact category/area match as the initial rule; show the matched area, category, report count, and a short reason for each suggestion.
- Prevent duplicate and stale suggestions when new reports arrive or members become resolved/cancelled. Define whether existing suggestions are refreshed or replaced and preserve coordinator decisions.
- Explain that a cluster means “possibly the same incident” and requires human review.

**Checkpoint:** The seeded pairs produce suggestions with both taskful and taskless reports; resolving/cancelling members removes or refreshes stale suggestions without changing accepted/dismissed decisions or creating duplicate cards.

### Phase D — Add triage and location correction

**Implementation status:** Coordinators can correct area/category or mark a location uncertain, with a required note and a persistent actor/timestamp history. Dispositions support out-of-scope and duplicate decisions, separate from task status and cluster review. Cluster suggestions only include known, certain areas and the supported drainage/flood-risk category; report details explain exclusion.

- Allow a coordinator to correct a report's area/category or flag its location as unknown/uncertain.
- Add an out-of-scope or duplicate disposition with a reason, actor, and timestamp; keep this separate from task cancellation and cluster dismissal.
- Require valid area/category values for clustering and explain when a report is excluded due to missing location.

**Checkpoint:** Incorrect or incomplete reports can be corrected or closed with a visible reason and full audit history; cluster eligibility is clear. Apply migration `0009_report_triage` before deploying the coordinator corrections.

### Phase E — Improve operational visibility and safeguards

**Implementation status:** SMS inbox poll outcomes now persist a heartbeat with last attempt, last success, and error state; the dashboard shows healthy, stale, failed, or unreported worker status. SMS callback failures get a masked-sender error log, outbound delivery outcomes remain recorded in logs/task history, and report rows/details distinguish demo data from non-demo submissions. Existing unique task-per-report and cluster fingerprint constraints, conflict recovery, and serialized cluster refreshes provide duplicate protection. Automated test coverage remains open because the repository currently has no test suite.

- Surface failed intake processing, SMS delivery outcomes, and background-worker health in logs or an operator-facing status area.
- Make demo/live provenance clear for reports and notifications.
- Make task creation and cluster generation safe under concurrent requests; enforce one task per report and prevent duplicate suggestions at the database level.
- Add backend and frontend coverage for recovery, state transitions, cluster eligibility, and duplicate requests.

**Checkpoint:** Operators can diagnose a stuck report or notification, and repeated/concurrent actions preserve one consistent report/task/cluster state.

### Suggested delivery order

Ship Phases A–C first to restore the coordinator's core report-to-response path. Follow with Phase D for data quality, then Phase E for production-style safeguards and visibility. Keep nearby-area clustering deferred until trusted locality adjacency data is available.

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
