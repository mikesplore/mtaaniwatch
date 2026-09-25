# MtaaniWatch Demo Runbook

Use this checklist to rehearse the resident-to-coordinator report flow. Sandbox delivery depends on Africa's Talking account and network availability; the dashboard records whether a notification was accepted by the API or shown in simulated mode.

## 1. Prepare the local demo

From the project directory:

```bash
rtk .venv/bin/alembic upgrade head
rtk .venv/bin/python -m scripts.seed_demo_data
```

The seed command is idempotent and inserts missing sample areas, crews, reports, and task histories. It does not delete or reset records that already exist.

## 2. Start the backend and SMS worker

Terminal 1:

```bash
rtk .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Terminal 2:

```bash
rtk .venv/bin/python -m scripts.poll_sms --interval 20
```

Open the coordinator dashboard at `https://admin.mikesplore.me/dashboard` or `http://localhost:8000/dashboard`. Confirm `/health/ready` reports that the database is connected.

## 3. Rehearse resident intake

Send a new SMS to the Africa's Talking Sandbox shortcode configured for the app. Example:

> Kuna mifereji imeziba Kongowea karibu na supermarket. Maji hayapiti na magari hayawezi kupita.

The resident should receive a concise confirmation in Swahili. Reply `NDIYO` to confirm. The system should send a report reference and save an unverified report with a task in `reported` status.

An English rehearsal message:

> A drain is blocked in Kongowea near the supermarket. Water is pooling and cars cannot pass.

Confirm with `YES`.

## 4. Rehearse coordinator response

1. Refresh the dashboard and find the new report by reference.
2. Review the reported area, landmark, impact, and unverified label.
3. Assign a demo crew.
4. Mark the task in progress, then resolved.
5. Check status history and the SMS notification badge. `SMS accepted` means Africa's Talking accepted the request; it does not confirm handset delivery. `SMS simulated` means the dashboard recorded a demo update without successful provider delivery.

Use **Find possible clusters** to generate suggestions from active reports with the same category and area. Accept or dismiss suggestions only after coordinator review.

## 5. Backup plan

If SMS delivery is unavailable, show the intake/polling logs and use the seeded reports to demonstrate assignment, task status history, cluster review, and simulated notification status. Re-run the idempotent seed command to restore any missing demo rows.
