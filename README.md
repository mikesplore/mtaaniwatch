# MtaaniWatch

**Turning community reports into coordinated disaster response.**

MtaaniWatch is a community incident reporting and field-response coordination prototype. Residents can report local hazards using basic-phone channels; the system structures and groups reports, helps coordinators assign field work, and sends residents status updates.

> **Demo scope:** Build a focused prototype for drainage obstruction and flood-risk reports in Mombasa. MtaaniWatch is a hackathon project, not an official county service. Demo reports, locations, crews, and resolution updates may be simulated.

## The problem

Residents can see drainage obstructions and flood risks before response teams do, but reports can be fragmented across calls and messages. A report is useful only if it can be understood, located, prioritized for human review, assigned, and followed through to an update for the person who raised it.

## Product promise

**See a problem. Report it. Track the response.**

The core differentiator is the complete report-to-resolution loop—not a standalone chatbot or map:

1. A resident submits a drainage obstruction or flood-risk report through USSD or SMS.
2. AI extracts a concise summary, issue type, location or landmark, and stated impact.
3. The resident confirms or corrects the key details.
4. Similar reports in the same area appear together as a *possible incident cluster* for coordinator review.
5. A coordinator assigns a task to a field crew and updates its status.
6. When the task is marked resolved, the resident receives an SMS update.

## Who it serves

- **Residents:** report an issue and receive a reference and status updates without needing a smartphone app or mobile data.
- **Coordinators:** review incoming reports, spot patterns, and assign work.
- **Field crews:** see their assigned tasks and update task status.

## Two-day MVP

### Must build

- One focused incident type: **drainage and flood risk**. It includes blocked or silted drains, gutters, manholes, culverts and waterways; flooding or standing water; and waste, silt, walls, or other obstructions affecting water flow. Unrelated issues such as garbage-only collection and streetlights are out of scope.
- A short SMS intake flow plus an Africa's Talking Voice IVR that records a spoken report, transcribes it, and asks the resident to confirm by SMS.
- Groq-powered extraction of report text into structured fields, with a human-readable fallback if AI is unavailable.
- A resident confirmation step for the interpreted location and issue.
- A coordinator dashboard with seeded reports, possible clusters, area, severity cues, and status.
- Manual task assignment and status progression: **Reported → Assigned → In progress → Resolved**.
- SMS receipt/reference and resolution update (live sandbox if available; simulated fallback for demo reliability).
- Clearly labeled sample/demo data and unverified reports.

### Explicitly out of scope for the first demo

- Crew-to-crew chat.
- Automated dispatch or AI decisions about whether a report is true or safe.
- Claims of live county, emergency-service, weather, or network integration.
- Unrelated incident categories, advanced GIS, or real-time flood prediction.
- Outbound voice campaigns, agent call-center features, and long-form call transcription.

## Suggested architecture

```text
Resident
  └─ Africa's Talking Voice or SMS
       └─ FastAPI webhook
            ├─ Groq Whisper: transcribe recorded voice; Groq LLM: extract report fields
            ├─ Database: reports, clusters, tasks, status history
            └─ SMS: receipt and status updates

Coordinator dashboard ── FastAPI ── Database
Field crew task view ─── FastAPI ── Database
```

Keep the model's job narrow: parse and summarize text. Use application rules for validation and status transitions. Keep a human coordinator in control of assignment and resolution. Treat any clustering as a suggestion requiring review, not proof that reports describe the same verified event.

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

## Build sequence

### Day 1 — Make the loop work

1. Create the backend data model and seed realistic demo reports, areas, and mock crews.
2. Build the resident intake endpoint and dashboard list/map view using mock locations.
3. Add Groq extraction for category, area/landmark, impact, language, and summary. Validate the response and handle malformed output.
4. Add resident confirmation/correction and a report reference.
5. Add coordinator assignment and task status updates.

### Day 2 — Connect, polish, rehearse

1. Connect the most dependable Africa's Talking channel (SMS or USSD) using its webhook.
2. Send an acknowledgment and resolution update; retain a visible simulated mode in case sandbox delivery fails.
3. Add possible incident grouping by nearby/mock area and similar category; let the coordinator accept or dismiss a cluster.
4. Polish the task workflow and ensure every dashboard action is visible in the demo.
5. Rehearse the complete story with a prepared report and a backup seeded dataset.

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

## Stack direction

- **Backend:** Python with FastAPI.
- **Telecom:** Africa's Talking SMS and inbound Voice IVR; USSD can be added later.
- **AI:** Groq for text extraction and concise summaries.
- **Storage:** choose the simplest dependable database for the two-day build; PostgreSQL is suitable if already set up. Avoid adding Redis unless the working flow needs it.
- **Frontend:** a simple responsive coordinator dashboard; prioritize readable incident and task states over map complexity.

## Configuration and data safety

Keep Africa's Talking and Groq credentials in environment variables; never commit secrets. Minimize personal data in the prototype, avoid showing full phone numbers on public dashboard screens, and use seeded or consented demo data. Do not represent this prototype as an official county service.

## Backend development

The backend uses FastAPI, PostgreSQL, SQLAlchemy, and Alembic. Configure the local database connection in `.env` using `DATABASE_URL` and, when needed, `DATABASE_PASSWORD`. Do not commit `.env`.

Open the coordinator dashboard at `/dashboard`. It displays reports and task history, supports crew assignment and status changes, and lets coordinators review possible incident clusters. Use **Find possible clusters** to group active reports that share a category and area. Groups remain suggestions until accepted or dismissed by a coordinator. When a task is resolved, the backend sends a resident SMS when possible and records whether Africa's Talking accepted it or the update was simulated. API acceptance does not confirm handset delivery.

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

For voice intake, configure an Africa's Talking Virtual Voice Number callback to `https://admin.mikesplore.me/webhooks/africastalking/voice`. Set `AT_PUBLIC_BASE_URL=https://admin.mikesplore.me` so keypad and recording callbacks use the public tunnel URL. Set `AT_WEBHOOK_TOKEN` and register the initial Voice callback with `?token=<value>`; the app carries that token into follow-up callbacks. The caller selects English or Kiswahili, consents to recording, and describes the drainage/flood issue. Africa's Talking posts the recording URL to `/webhooks/africastalking/voice/recording`; Groq Whisper transcribes it and the report enters the normal SMS confirmation flow. This uses one transcription request and one report-extraction request per recorded report. Configure `GROQ_STT_MODEL` to select the speech-to-text model. Voice Sandbox interactions are through Africa's Talking Simulator, not a handset.

If inbound callbacks are unavailable, run the inbox poller in a second terminal after applying migrations:

```bash
rtk .venv/bin/alembic upgrade head
rtk .venv/bin/python -m scripts.poll_sms --interval 20
```

On its first start, the poller records the current latest inbox message ID and skips existing Sandbox test messages. It then processes new messages and stores its cursor in PostgreSQL, so restarts do not replay already handled messages. Keep the poller running while testing; stop it with `Ctrl+C`.

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
