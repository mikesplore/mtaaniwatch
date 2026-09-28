# MtaaniWatch

**Community reports made actionable and followed through.**

MtaaniWatch is a prototype for capturing local drainage and flood-risk reports, organizing them for coordinator review, and tracking response work. It focuses on the gap between a resident noticing a blocked drain or flooding and the response team having a clear, trackable report to act on.

The project currently focuses on Mombasa and supports resident intake by SMS and an inbound voice flow. Coordinators use a web dashboard to review reports, create response tasks, assign crews, track progress, and identify reports that may describe the same incident. Residents can receive a report reference and a response update by SMS.

> **Prototype scope:** MtaaniWatch is a hackathon project, not an official county service. Some reports, areas, crews, or SMS outcomes used in the demo are sample or simulated data. A report or cluster is not proof that an incident is verified.

## How it works

At a high level, the app connects three parts of a response loop:

1. **A resident reports an issue.** They describe a drainage or flood-risk problem by SMS, or call the voice line, choose English or Kiswahili, and leave a recorded description. The voice recording is transcribed before processing.
2. **The system prepares a report.** It extracts a concise summary, issue category, area or landmark, language, and any stated impacts. AI extraction is optional; a local fallback is used when the service is unavailable. The SMS flow asks the resident to confirm the interpreted details before saving the report.
3. **A coordinator reviews it.** The report appears in the web console with its review state and response-task state shown separately. The coordinator can correct its area or issue category, flag an uncertain location, verify the report, create a response task, or record an out-of-scope or duplicate decision with a reason. Coordinator decisions are timestamped in the report history.
4. **Response work is tracked.** A coordinator assigns a task to a crew and advances it through reported, assigned, in progress, and resolved. Actions are recorded in task history.
5. **Related reports can be reviewed together.** The app can suggest possible clusters for active reports with the same issue category and area. A cluster is only a grouping suggestion; a coordinator decides whether it is useful.
6. **The resident gets an update.** When the task is marked resolved, the app attempts to send a status SMS. The console records whether the provider accepted the request or the update was simulated; provider acceptance does not prove delivery to the handset.

## Who it serves

- **Residents:** report an issue and get a reference and status updates without requiring a smartphone app or mobile data.
- **Coordinators:** review reports, decide what needs a response, assign work, and track progress.
- **Field crews:** are represented in the prototype as selectable assignees on response tasks. A separate crew-facing application is not currently provided.

## High-level architecture

```text
Resident
  ├─ SMS ───────────────┐
  └─ Voice recording ───┴─ Africa's Talking callbacks
                              │
                              ▼
                         FastAPI backend
                         ├─ Intake state and confirmation
                         ├─ Optional Groq transcription/extraction
                         ├─ PostgreSQL reports, areas, tasks, and history
                         └─ SMS acknowledgments and status updates
                              ▲
                              │ API
                    Coordinator web dashboard
                    ├─ Review and disposition
                    ├─ Task creation and crew assignment
                    └─ Cluster suggestions and review
```

The backend applies validation and workflow rules; AI assists with transcription and structuring resident-provided information. Coordinators remain responsible for verification, assignment, and decisions about cluster suggestions.

## Current prototype boundaries

- Focused on drainage obstruction and flood-risk reports in Mombasa.
- SMS and inbound voice are implemented through Africa's Talking callbacks; USSD is not currently implemented.
- Groq can transcribe voice recordings and extract report fields. If credentials or the service are unavailable, report extraction has a local fallback; voice transcription requires the configured service.
- Crew selection and response tracking are available in the coordinator dashboard; there is no separate crew app or automated dispatch.
- Cluster suggestions match active reports by exact category and area. They do not establish that reports refer to the same verified event.
- SMS delivery, sample records, locations, and crews may be simulated in the demo.

## Main capabilities

- Bilingual SMS report intake and resident confirmation.
- Inbound voice intake with English/Kiswahili selection, recording, transcription, and SMS confirmation.
- Coordinator dashboard for report review, verification, out-of-scope decisions, and task creation.
- Crew assignment and task progression: **Reported → Assigned → In progress → Resolved**.
- Possible incident cluster suggestions for coordinator review.
- Resident report references and resolution notifications by SMS where provider delivery is available.

## Scope and decision rules

The prototype focuses on drainage obstruction and flood risk: blocked or silted drains, gutters, manholes, culverts and waterways; flooding or standing water; and obstructions that affect water flow. Garbage-only collection, streetlights, general road damage, and unrelated incidents are outside this demo's intake scope.

AI is used to transcribe and structure information residents provide. It does not determine whether a report is true, how dangerous an incident is, or what action a crew should take. Missing or uncertain details are shown for coordinator review. Coordinators control report verification, task assignment, task status, and cluster decisions.

### Initial report shape

```json
{
  "category": "drainage_flooding",
  "area": "Kisauni",
  "landmark": "near the school",
  "impact_reported": ["water on road", "homes affected"],
  "summary": "Drain reported blocked near the school; water is on the road.",
  "language": "sw",
  "confidence": 0.82,
  "status": "reported",
  "verified": false
}
```

Only store fields supported by the resident's report. A model confidence score is a parsing hint, not a measure of real-world danger.

## Five-minute demo script

1. Submit a short Swahili/English drainage or flood-risk report, such as: “Kuna mfereji imeziba karibu na shule; maji iko kwa barabara.”
2. Show the AI extraction and have the resident confirm the area/landmark.
3. Show the report appear on the dashboard and join a possible nearby cluster.
4. Coordinator reviews it and assigns a mock crew task.
5. Crew marks it in progress, then resolved.
6. Show the resident's SMS update and the task's status history.

Explain that the reports, locations, and crews are demo data where simulated, and that clusters are unverified until reviewed. The value is making community reports actionable and closing the feedback loop.

## Success criteria

- A report can travel from resident channel to dashboard without manual database editing.
- AI output is structured, validated, and correctable by the resident or coordinator.
- A coordinator can assign and close a task.
- A resident-facing acknowledgment and resolution update are shown or sent.
- The demo remains understandable and complete if an external API is unavailable.

## Configuration and data safety

Keep Africa's Talking and Groq credentials in environment variables; never commit secrets. Minimize personal data in the prototype, avoid showing full phone numbers on public dashboard screens, and use seeded or consented demo data. Do not represent this prototype as an official county service.

## Backend development

The backend uses FastAPI, PostgreSQL, SQLAlchemy, and Alembic. Configure the local database connection in `.env` using `DATABASE_URL` and, when needed, `DATABASE_PASSWORD`. Do not commit `.env`.

Open the coordinator dashboard at `/dashboard`. It displays reports and task history, supports crew assignment and status changes, and lets coordinators review possible incident clusters. Use **Find possible clusters** to group active reports that share a category and area. Groups remain suggestions until accepted or dismissed by a coordinator. When a task is resolved, the backend sends a resident SMS when possible and records whether Africa's Talking accepted it or the update was simulated. API acceptance does not confirm handset delivery.

The dashboard's inbox-worker indicator uses the most recent poller heartbeat: it shows healthy, stale, failed, or unknown until the SMS poller reports in. Report rows mark demo/sandbox data separately from non-demo submissions. Notification outcomes are preserved in the task history and service logs.

For reports that do not yet have a response task, open the report details and choose **Create response task**, or use the bulk recovery button in **Tasks** to create tasks for all taskless reports. Verification is a separate coordinator action and is not required to start response work.

Follow [DEMO_RUNBOOK.md](DEMO_RUNBOOK.md) to start the backend and SMS worker and rehearse the Swahili/English resident flow through task resolution.

The seed data includes a separate `Kongowea` area as well as other Mombasa localities. Re-run the idempotent seed command below to add missing demo reference data without duplicating the seeded reports.

Run database migrations with:

```bash
rtk .venv/bin/alembic upgrade head
```

Load the repeatable, clearly labeled Mombasa demo areas, crews, reports, and task histories with:

```bash
rtk .venv/bin/python -m scripts.seed_demo_data
```

The Africa's Talking inbound SMS callback is `/webhooks/africastalking/sms`. Configure the sandbox's incoming-message callback to `https://admin.mikesplore.me/webhooks/africastalking/sms`. Optionally set `AT_WEBHOOK_TOKEN` and append `?token=<value>` to the callback URL to restrict who can submit callbacks. Set `AT_API_KEY` to enable outbound SMS through the official Python SDK; `AT_USERNAME` should be `sandbox` for Sandbox. Set `AT_SHORTCODE` to the Sandbox short code shown in your SMS dashboard so replies to incoming on-demand SMS can include the associated `linkId`. Set `GROQ_API_KEY` to enable structured extraction; without it, the webhook uses a local text/area fallback. `AT_SENDER_ID` is for standard outbound SMS, and `GROQ_MODEL` selects the extraction model.

For voice intake, configure an Africa's Talking Voice number callback to `https://admin.mikesplore.me/webhooks/africastalking/voice`. Set `AT_PUBLIC_BASE_URL=https://admin.mikesplore.me` so keypad and recording callbacks use the public URL. Set `AT_WEBHOOK_TOKEN` and register the initial Voice callback with `?token=<value>`; the app carries that token into follow-up callbacks. The caller selects English or Kiswahili, records a drainage/flood report, and ends the recording with `#`. That key should stop recording immediately; `maxLength="45"` is only the upper time limit. Africa's Talking can post the recording callback to `/webhooks/africastalking/voice/recording`; if the dashboard supports a separate Voice Events URL, set it to `/webhooks/africastalking/voice/events`. Completion events sent to the language callback are also recognized, so they won't restart the menu. The app remembers the selected language per call and processes a recording only once, including recording URLs hosted on Africa's Talking's `at-internal.com` domain. Groq Whisper transcribes it and the report enters the normal SMS confirmation flow. This uses one transcription request and one report-extraction request per recorded report. Configure `GROQ_STT_MODEL` to select the speech-to-text model. Africa's Talking currently says Voice Sandbox is not operational; request a Voice Test Number in the live dashboard to test the beep, recording, and keypad callbacks.

Use one inbound SMS transport at a time. Prefer the Africa's Talking **Incoming Messages** callback above; run the inbox poller only when that callback is unavailable, since polling the same inbox alongside callbacks can produce duplicate replies if the provider omits or changes message IDs. To use polling, run it in a second terminal after applying migrations:

```bash
rtk .venv/bin/alembic upgrade head
rtk .venv/bin/python -m scripts.poll_sms --interval 20
```

On its first start, the poller records the current latest inbox message ID and skips existing Sandbox test messages. It then processes new messages and stores its cursor in PostgreSQL, so restarts do not replay already handled messages. Keep it running while using polling; stop it with `Ctrl+C` before switching back to callback intake.

After changing SQLAlchemy models, create a migration and review it before applying:

```bash
rtk .venv/bin/alembic revision --autogenerate -m "describe schema change"
rtk .venv/bin/alembic upgrade head
```

Check whether the models and database schema differ with:

```bash
rtk .venv/bin/alembic check
```

## Next steps

1. Rehearse the report → confirmation → dashboard → assignment → resolution flow.
2. Verify the Africa's Talking Sandbox sends resident updates where delivery is available; keep the simulated mode for failures.
3. Add nearby-area clustering only after maintaining trusted locality adjacency data.
