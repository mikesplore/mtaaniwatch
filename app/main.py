import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from xml.sax.saxutils import escape, quoteattr

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import check_database_connection, get_db
from app.intake import parse_callback, process_inbound_sms, send_resolution_sms
from app.models import (
    Area,
    ClusterReviewStatus,
    Crew,
    IncidentCluster,
    Report,
    Task,
    TaskStatus,
    TaskStatusHistory,
)
from app.schemas import (
    AreaRead,
    ClusterReviewUpdate,
    ClusterSuggestionResult,
    CrewRead,
    IncidentClusterRead,
    ReportCreate,
    ReportRead,
    ReportVerificationUpdate,
    TaskAssign,
    TaskRead,
    TaskStatusUpdate,
)
from app.voice import transcribe_voice_report


app = FastAPI(title=settings.app_name, version="0.1.0")
logger = logging.getLogger(__name__)
FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
if (FRONTEND_DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")


@app.get("/", include_in_schema=False)
def home() -> RedirectResponse:
    return RedirectResponse(url="/dashboard")


@app.get("/dashboard", response_class=FileResponse, tags=["coordinator dashboard"])
def coordinator_dashboard() -> FileResponse:
    if FRONTEND_INDEX.is_file():
        return FileResponse(FRONTEND_INDEX, media_type="text/html")
    return FileResponse(Path(__file__).parent / "static" / "dashboard.html", media_type="text/html")


@app.post("/webhooks/africastalking/sms", response_class=PlainTextResponse, tags=["resident intake"])
async def africastalking_sms_webhook(
    request: Request, db: Session = Depends(get_db)
) -> PlainTextResponse:
    if settings.at_webhook_token and request.query_params.get("token") != settings.at_webhook_token:
        raise HTTPException(status_code=403, detail="Invalid webhook token")
    fields = parse_callback(await request.body())
    sender = fields.get("from", "").strip()
    masked_sender = f"***{sender[-4:]}" if sender else "missing"
    logger.info(
        "Africa's Talking SMS callback received: fields=%s sender=%s text_length=%d message_id=%s",
        sorted(fields),
        masked_sender,
        len(fields.get("text", "").strip()),
        fields.get("id") or fields.get("messageId") or "missing",
    )
    process_inbound_sms(fields, db)
    return PlainTextResponse("Received")


def _check_voice_webhook_token(request: Request) -> None:
    if settings.at_webhook_token and request.query_params.get("token") != settings.at_webhook_token:
        raise HTTPException(status_code=403, detail="Invalid webhook token")


def _voice_callback_url(request: Request, path: str, **query: str) -> str:
    base_url = (settings.at_public_base_url or str(request.base_url)).rstrip("/")
    if settings.at_webhook_token:
        query["token"] = settings.at_webhook_token
    return f"{base_url}{path}?{urlencode(query)}" if query else f"{base_url}{path}"


def _voice_xml(body: str) -> Response:
    return Response(
        content=f'<?xml version="1.0" encoding="UTF-8"?><Response>{body}</Response>',
        media_type="application/xml",
    )


def _voice_language_menu(request: Request, retry: int = 0) -> Response:
    callback_url = _voice_callback_url(
        request, "/webhooks/africastalking/voice/language", retry=str(retry)
    )
    prompt = (
        "Welcome to MtaaniWatch. This call may be recorded and transcribed to prepare your report. "
        "Press 1 for English, or press 2 for Kiswahili. "
        "Karibu MtaaniWatch. Piga 1 kwa Kiingereza au 2 kwa Kiswahili."
    )
    return _voice_xml(
        f"<GetDigits numDigits=\"1\" timeout=\"12\" finishOnKey=\"#\" callbackUrl={quoteattr(callback_url)}>"
        f"<Say>{escape(prompt)}</Say></GetDigits>"
        "<Say>We did not receive a selection. Goodbye.</Say>"
    )


@app.post("/webhooks/africastalking/voice", tags=["resident voice intake"])
async def africastalking_voice_webhook(request: Request) -> Response:
    _check_voice_webhook_token(request)
    fields = parse_callback(await request.body())
    caller = fields.get("callerNumber", "")
    session_id = fields.get("sessionId", "missing")
    masked_caller = f"***{caller[-4:]}" if caller else "missing"
    logger.info("Africa's Talking Voice call received: caller=%s session=%s", masked_caller, session_id)
    return _voice_language_menu(request)


@app.post("/webhooks/africastalking/voice/language", tags=["resident voice intake"])
async def africastalking_voice_language(request: Request) -> Response:
    _check_voice_webhook_token(request)
    fields = parse_callback(await request.body())
    digit = fields.get("dtmfDigits", "").strip()
    language = {"1": "en", "2": "sw"}.get(digit)
    if language is None:
        retry = int(request.query_params.get("retry", "0"))
        if retry < 1:
            return _voice_language_menu(request, retry=retry + 1)
        return _voice_xml("<Say>We did not receive a valid choice. Goodbye.</Say>")

    callback_url = _voice_callback_url(
        request, "/webhooks/africastalking/voice/recording", language=language
    )
    prompt = (
        "After the beep, describe the drainage or flooding problem and give its Mombasa area or a nearby landmark. "
        "Press the hash key when you are done. You have up to 45 seconds."
        if language == "en"
        else "Baada ya mlio, eleza tatizo la mfereji au mafuriko na utaje eneo la Mombasa au alama ya karibu. "
        "Bonyeza alama ya reli ukimaliza. Una sekunde 45."
    )
    logger.info("Voice caller selected language=%s", language)
    return _voice_xml(
        f"<Say>{escape(prompt)}</Say>"
        f"<Record finishOnKey=\"#\" maxLength=\"45\" timeout=\"8\" trimSilence=\"true\" "
        f"playBeep=\"true\" callbackUrl={quoteattr(callback_url)}/>"
    )


@app.post("/webhooks/africastalking/voice/recording", tags=["resident voice intake"])
async def africastalking_voice_recording(
    request: Request, background_tasks: BackgroundTasks
) -> Response:
    _check_voice_webhook_token(request)
    fields = parse_callback(await request.body())
    phone = fields.get("callerNumber", "").strip()
    session_id = fields.get("sessionId", "").strip()
    recording_url = fields.get("recordingUrl") or fields.get("recordingURL") or fields.get("recording_url", "")
    language = request.query_params.get("language", "en")
    if language not in {"en", "sw"}:
        language = "en"
    masked_caller = f"***{phone[-4:]}" if phone else "missing"
    if not phone or not session_id or not recording_url:
        logger.warning(
            "Voice recording callback missing required data: caller=%s session_present=%s recording_present=%s",
            masked_caller,
            bool(session_id),
            bool(recording_url),
        )
        closing = "Hatukuweza kupokea ujumbe wako. Tafadhali jaribu tena." if language == "sw" else "We could not receive your recording. Please try again."
        return _voice_xml(f"<Say>{escape(closing)}</Say>")

    logger.info("Voice recording received: caller=%s session=%s", masked_caller, session_id)
    background_tasks.add_task(transcribe_voice_report, phone, session_id, recording_url, language)
    closing = (
        "Asante. Tumepokea ujumbe wako. Tutakutumia SMS ili uthibitishe maelezo ya ripoti yako. "
        "Unaweza kukata simu sasa."
        if language == "sw"
        else "Thank you. We received your report. We will text you to confirm its details. You may hang up now."
    )
    return _voice_xml(f"<Say>{escape(closing)}</Say>")


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/health/ready", tags=["health"])
def readiness() -> dict[str, str]:
    try:
        check_database_connection()
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
    return {"status": "ready", "database": "connected"}


@app.get("/areas", response_model=list[AreaRead], tags=["reference data"])
def list_areas(db: Session = Depends(get_db)) -> list[Area]:
    return list(db.query(Area).order_by(Area.name).all())


@app.get("/crews", response_model=list[CrewRead], tags=["reference data"])
def list_crews(db: Session = Depends(get_db)) -> list[Crew]:
    return list(db.query(Crew).order_by(Crew.name).all())


@app.post("/reports", response_model=ReportRead, status_code=201, tags=["reports"])
def create_report(payload: ReportCreate, db: Session = Depends(get_db)) -> Report:
    report = Report(**payload.model_dump(), reference="pending")
    if payload.area:
        report.area_ref = db.query(Area).filter(Area.name.ilike(payload.area)).first()
    db.add(report)
    db.flush()
    report.reference = f"MW-{report.id:06d}"
    task = Task(report=report, status=TaskStatus.REPORTED)
    task.history.append(TaskStatusHistory(status=TaskStatus.REPORTED, note="Report received"))
    db.add(task)
    db.commit()
    db.refresh(report)
    return report


@app.get("/reports", response_model=list[ReportRead], tags=["reports"])
def list_reports(db: Session = Depends(get_db)) -> list[Report]:
    return list(db.query(Report).order_by(Report.created_at.desc()).all())


@app.get("/reports/{reference}", response_model=ReportRead, tags=["reports"])
def get_report(reference: str, db: Session = Depends(get_db)) -> Report:
    report = db.query(Report).filter(Report.reference == reference).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    return report


@app.patch("/reports/{reference}/verification", response_model=ReportRead, tags=["reports"])
def update_report_verification(
    reference: str, payload: ReportVerificationUpdate, db: Session = Depends(get_db)
) -> Report:
    report = db.query(Report).filter(Report.reference == reference).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    report.verified = payload.verified
    db.commit()
    db.refresh(report)
    return report


@app.get("/tasks", response_model=list[TaskRead], tags=["tasks"])
def list_tasks(db: Session = Depends(get_db)) -> list[Task]:
    return list(db.query(Task).order_by(Task.created_at.desc()).all())


@app.post(
    "/clusters/suggest",
    response_model=ClusterSuggestionResult,
    tags=["possible incident clusters"],
)
def suggest_incident_clusters(db: Session = Depends(get_db)) -> ClusterSuggestionResult:
    active_reports = (
        db.query(Report)
        .join(Task, Task.report_id == Report.id)
        .filter(
            Report.area_id.is_not(None),
            Task.status.in_([TaskStatus.REPORTED, TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS]),
        )
        .all()
    )
    groups: dict[tuple[str, int], list[Report]] = defaultdict(list)
    for report in active_reports:
        groups[(report.category, report.area_id)].append(report)

    created = 0
    for (category, area_id), reports in groups.items():
        if len(reports) < 2:
            continue
        reports.sort(key=lambda item: item.id)
        fingerprint = f"{category}:{area_id}:{','.join(str(item.id) for item in reports)}"
        existing = db.query(IncidentCluster.id).filter(IncidentCluster.fingerprint == fingerprint).first()
        if existing:
            continue
        db.add(
            IncidentCluster(
                category=category,
                area_id=area_id,
                fingerprint=fingerprint,
                status=ClusterReviewStatus.SUGGESTED,
                reports=reports,
            )
        )
        created += 1

    db.commit()
    return ClusterSuggestionResult(created=created)


@app.get("/clusters", response_model=list[IncidentClusterRead], tags=["possible incident clusters"])
def list_incident_clusters(db: Session = Depends(get_db)) -> list[IncidentCluster]:
    return list(db.query(IncidentCluster).order_by(IncidentCluster.created_at.desc()).all())


@app.patch(
    "/clusters/{cluster_id}",
    response_model=IncidentClusterRead,
    tags=["possible incident clusters"],
)
def review_incident_cluster(
    cluster_id: int, payload: ClusterReviewUpdate, db: Session = Depends(get_db)
) -> IncidentCluster:
    cluster = db.query(IncidentCluster).filter(IncidentCluster.id == cluster_id).first()
    if cluster is None:
        raise HTTPException(status_code=404, detail="Cluster suggestion not found")
    if payload.status not in {ClusterReviewStatus.ACCEPTED, ClusterReviewStatus.DISMISSED}:
        raise HTTPException(status_code=422, detail="A suggestion can only be accepted or dismissed")
    if cluster.status != ClusterReviewStatus.SUGGESTED:
        raise HTTPException(status_code=409, detail="This cluster suggestion has already been reviewed")

    cluster.status = payload.status
    cluster.review_note = payload.note
    cluster.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(cluster)
    return cluster


@app.post("/tasks/{task_id}/assign", response_model=TaskRead, tags=["tasks"])
def assign_task(task_id: int, payload: TaskAssign, db: Session = Depends(get_db)) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.REPORTED:
        raise HTTPException(status_code=409, detail="Only reported tasks can be assigned")
    crew = db.query(Crew).filter(Crew.name == payload.crew_name).first()
    if crew is None:
        raise HTTPException(status_code=404, detail="Crew not found")
    task.crew_name = payload.crew_name
    task.crew_ref = crew
    task.status = TaskStatus.ASSIGNED
    task.history.append(TaskStatusHistory(status=TaskStatus.ASSIGNED, note=f"Assigned to {payload.crew_name}"))
    db.commit()
    db.refresh(task)
    return task


@app.patch("/tasks/{task_id}/status", response_model=TaskRead, tags=["tasks"])
def update_task_status(
    task_id: int, payload: TaskStatusUpdate, db: Session = Depends(get_db)
) -> Task:
    task = db.query(Task).filter(Task.id == task_id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="Task not found")

    allowed_transitions = {
        TaskStatus.REPORTED: {TaskStatus.CANCELLED},
        TaskStatus.ASSIGNED: {TaskStatus.IN_PROGRESS},
        TaskStatus.IN_PROGRESS: {TaskStatus.RESOLVED},
    }
    if payload.status not in allowed_transitions.get(task.status, set()):
        raise HTTPException(status_code=409, detail=f"Cannot move task from {task.status} to {payload.status}")

    task.status = payload.status
    status_event = TaskStatusHistory(status=payload.status, note=payload.note)
    task.history.append(status_event)
    db.commit()
    if payload.status == TaskStatus.RESOLVED:
        delivery = send_resolution_sms(task.report)
        if delivery == "accepted":
            outcome = "resolution SMS accepted by Africa's Talking; handset delivery is unconfirmed"
        elif delivery == "simulated":
            outcome = "resolution SMS shown in simulated mode; not delivered"
        else:
            outcome = "provider send failed; resolution update shown in simulated mode"
        status_event.note = f"{payload.note}. {outcome}" if payload.note else outcome.capitalize()
        db.commit()
    db.refresh(task)
    return task
