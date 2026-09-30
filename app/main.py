import logging
import asyncio
from contextlib import asynccontextmanager
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from xml.sax.saxutils import escape, quoteattr

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import check_database_connection, get_db
from app.intake import parse_callback, process_inbound_sms, send_in_progress_sms, send_resolution_sms
from app.models import (
    Area,
    CLUSTERABLE_REPORT_CATEGORIES,
    ClusterReviewStatus,
    Crew,
    IncidentCluster,
    Report,
    ReportReviewEvent,
    Task,
    TaskStatus,
    TaskStatusHistory,
    VoiceIntakeSession,
    WorkerHeartbeat,
)
from app.schemas import (
    AreaRead,
    ClusterReviewUpdate,
    ClusterSuggestionResult,
    CrewRead,
    IncidentClusterRead,
    ReportCreate,
    ReportDispositionUpdate,
    ReportRead,
    ReportTriageUpdate,
    ReportVerificationUpdate,
    TaskAssign,
    TaskBackfillResult,
    TaskRead,
    TaskStatusUpdate,
)
from app.voice import transcribe_voice_report


@asynccontextmanager
async def lifespan(app: FastAPI):
    poller_task = None
    if settings.at_sms_polling_enabled:
        if settings.at_sms_poll_interval < 1:
            raise ValueError("AT_SMS_POLL_INTERVAL must be at least 1 second")
        from scripts.poll_sms import run_poller

        poller_task = asyncio.create_task(run_poller(settings.at_sms_poll_interval))
    try:
        yield
    finally:
        if poller_task is not None:
            poller_task.cancel()
            try:
                await poller_task
            except asyncio.CancelledError:
                pass


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
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
    try:
        process_inbound_sms(fields, db)
    except Exception:
        logger.exception(
            "Inbound SMS processing failed: sender=%s message_id=%s",
            masked_sender,
            fields.get("id") or fields.get("messageId") or "missing",
        )
        raise
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
        "Welcome to MtaaniWatch. Press 1 for English or 2 for Kiswahili."
        "Karibu MtaaniWatch. Piga 1 kwa Kiingereza au 2 kwa Kiswahili."
    )
    return _voice_xml(
        f"<GetDigits numDigits=\"1\" timeout=\"12\" callbackUrl={quoteattr(callback_url)}>"
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
async def africastalking_voice_language(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> Response:
    _check_voice_webhook_token(request)
    fields = parse_callback(await request.body())
    digit_value = next(
        (
            value
            for key, value in fields.items()
            if key.casefold() in {"dtmfdigits", "dtmfdigit", "digits"}
        ),
        "",
    )
    digit = digit_value.strip().removesuffix("#").strip()
    language = {"1": "en", "2": "sw"}.get(digit)
    recording_url = fields.get("recordingUrl") or fields.get("recordingURL") or fields.get("recording_url", "")
    if fields.get("callSessionState", "").casefold() == "completed" or recording_url:
        session_id = fields.get("sessionId", "").strip()
        session = db.get(VoiceIntakeSession, session_id) if session_id else None
        if recording_url:
            response_language = session.language if session else (language or "en")
            _queue_voice_transcription(fields, recording_url, response_language, background_tasks, db)
        return PlainTextResponse("Received")
    if language is None:
        logger.warning(
            "Voice language callback received no supported selection (fields=%s, dtmf=%r)",
            sorted(fields),
            digit_value[:4],
        )
        retry = int(request.query_params.get("retry", "0"))
        if retry < 1:
            return _voice_language_menu(request, retry=retry + 1)
        return _voice_xml("<Say>We did not receive a valid choice. Goodbye.</Say>")

    session_id = fields.get("sessionId", "").strip()
    caller_number = fields.get("callerNumber", "").strip()
    if session_id and caller_number:
        session = db.get(VoiceIntakeSession, session_id)
        if session is None:
            session = VoiceIntakeSession(
                session_id=session_id,
                caller_number=caller_number,
                language=language,
                recording_processed=False,
            )
            db.add(session)
        else:
            session.caller_number = caller_number
            session.language = language
        db.commit()

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
    request: Request, background_tasks: BackgroundTasks, db: Session = Depends(get_db)
) -> Response:
    _check_voice_webhook_token(request)
    fields = parse_callback(await request.body())
    phone = fields.get("callerNumber", "").strip()
    session_id = fields.get("sessionId", "").strip()
    recording_url = fields.get("recordingUrl") or fields.get("recordingURL") or fields.get("recording_url", "")
    session = db.get(VoiceIntakeSession, session_id) if session_id else None
    language = session.language if session else request.query_params.get("language", "en")
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

    if not _queue_voice_transcription(fields, recording_url, language, background_tasks, db):
        return PlainTextResponse("Received")
    logger.info("Voice recording received: caller=%s session=%s", masked_caller, session_id)
    closing = (
        "Asante. Tumepokea ujumbe wako. Tutakutumia SMS ili uthibitishe maelezo ya ripoti yako. "
        "Unaweza kukata simu sasa."
        if language == "sw"
        else "Thank you. We received your report. We will text you to confirm its details. You may hang up now."
    )
    return _voice_xml(f"<Say>{escape(closing)}</Say>")


def _queue_voice_transcription(
    fields: dict[str, str],
    recording_url: str,
    language: str,
    background_tasks: BackgroundTasks,
    db: Session,
) -> bool:
    phone = fields.get("callerNumber", "").strip()
    session_id = fields.get("sessionId", "").strip()
    if not phone or not session_id or not recording_url:
        logger.warning("Voice recording callback missing caller, session, or recording URL")
        return False
    session = db.get(VoiceIntakeSession, session_id)
    if session is None:
        session = VoiceIntakeSession(
            session_id=session_id,
            caller_number=phone,
            language=language if language in {"en", "sw"} else "en",
            recording_processed=True,
        )
        db.add(session)
        db.commit()
    else:
        if session.recording_processed:
            logger.info("Ignoring duplicate voice recording callback: session=%s", session_id)
            return False
        language = session.language
        session.recording_processed = True
        db.commit()
    logger.info("Queueing voice transcription: session=%s language=%s", session_id, language)
    background_tasks.add_task(transcribe_voice_report, phone, session_id, recording_url, language)
    return True


@app.post("/webhooks/africastalking/voice/events", tags=["resident voice intake"])
async def africastalking_voice_events(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
) -> PlainTextResponse:
    _check_voice_webhook_token(request)
    fields = parse_callback(await request.body())
    recording_url = fields.get("recordingUrl") or fields.get("recordingURL") or fields.get("recording_url", "")
    session_id = fields.get("sessionId", "").strip()
    session = db.get(VoiceIntakeSession, session_id) if session_id else None
    if recording_url:
        language = session.language if session else "en"
        _queue_voice_transcription(fields, recording_url, language, background_tasks, db)
    return PlainTextResponse("Received")


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


@app.get("/operations/health", tags=["operations"])
def operations_health(db: Session = Depends(get_db)) -> dict[str, object]:
    heartbeat = db.get(WorkerHeartbeat, "africastalking_sms_poller")
    if heartbeat is None:
        status = "not_reported"
    elif heartbeat.last_error:
        status = "error"
    elif datetime.now(timezone.utc) - heartbeat.last_attempt_at > timedelta(seconds=75):
        status = "stale"
    else:
        status = "healthy"
    return {
        "sms_poller": {
            "status": status,
            "last_attempt_at": heartbeat.last_attempt_at if heartbeat else None,
            "last_success_at": heartbeat.last_success_at if heartbeat else None,
            "last_error": heartbeat.last_error if heartbeat else None,
            "last_processed_count": heartbeat.last_processed_count if heartbeat else None,
        }
    }


@app.get("/areas", response_model=list[AreaRead], tags=["reference data"])
def list_areas(db: Session = Depends(get_db)) -> list[Area]:
    return list(db.query(Area).order_by(Area.name).all())


@app.get("/crews", response_model=list[CrewRead], tags=["reference data"])
def list_crews(db: Session = Depends(get_db)) -> list[Crew]:
    return list(db.query(Crew).order_by(Crew.name).all())


@app.post("/reports", response_model=ReportRead, status_code=201, tags=["reports"])
def create_report(payload: ReportCreate, db: Session = Depends(get_db)) -> Report:
    report = Report(**payload.model_dump(), reference="pending", location_uncertain=False)
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


@app.post("/reports/{reference}/task", response_model=TaskRead, status_code=201, tags=["tasks"])
def create_report_task(
    reference: str, response: Response, db: Session = Depends(get_db)
) -> Task:
    report = db.query(Report).filter(Report.reference == reference).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    existing = db.query(Task).filter(Task.report_id == report.id).first()
    if existing is not None:
        response.status_code = 200
        return existing
    task = _new_report_task(report, "Response task created by coordinator")
    db.add(task)
    try:
        db.commit()
    except IntegrityError:
        # The unique task.report_id constraint makes concurrent retries safe.
        db.rollback()
        existing = db.query(Task).filter(Task.report_id == report.id).first()
        if existing is not None:
            response.status_code = 200
            return existing
        raise
    db.refresh(task)
    return task


def _new_report_task(report: Report, note: str) -> Task:
    task = Task(report=report, status=TaskStatus.REPORTED)
    task.history.append(TaskStatusHistory(status=TaskStatus.REPORTED, note=note))
    return task


@app.post("/tasks/backfill", response_model=TaskBackfillResult, tags=["tasks"])
def backfill_report_tasks(db: Session = Depends(get_db)) -> TaskBackfillResult:
    reports = (
        db.query(Report)
        .outerjoin(Task, Task.report_id == Report.id)
        .filter(Task.id.is_(None))
        .order_by(Report.id)
        .all()
    )
    created = 0
    for report in reports:
        try:
            with db.begin_nested():
                db.add(_new_report_task(report, "Response task recovered by coordinator"))
                db.flush()
            created += 1
        except IntegrityError:
            # Another request created this report's task after the query.
            continue
    db.commit()
    return TaskBackfillResult(created=created)


@app.patch("/reports/{reference}/verification", response_model=ReportRead, tags=["reports"])
def update_report_verification(
    reference: str, payload: ReportVerificationUpdate, db: Session = Depends(get_db)
) -> Report:
    report = db.query(Report).filter(Report.reference == reference).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    report.verified = payload.verified
    report.review_events.append(
        ReportReviewEvent(
            action="verification",
            reason="Report marked verified" if payload.verified else "Report marked unverified",
            actor="Operations Admin",
        )
    )
    db.commit()
    db.refresh(report)
    return report


@app.patch("/reports/{reference}/disposition", response_model=ReportRead, tags=["reports"])
def update_report_disposition(
    reference: str, payload: ReportDispositionUpdate, db: Session = Depends(get_db)
) -> Report:
    report = db.query(Report).filter(Report.reference == reference).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.disposition is not None:
        raise HTTPException(status_code=409, detail="This report already has a disposition")
    report.disposition = payload.disposition
    report.disposition_reason = payload.reason
    report.disposition_actor = "Operations Admin"
    report.disposition_at = datetime.now(timezone.utc)
    report.review_events.append(
        ReportReviewEvent(
            action="disposition",
            reason=f"{payload.disposition}: {payload.reason}",
            actor="Operations Admin",
            details={"disposition": payload.disposition},
        )
    )
    db.commit()
    db.refresh(report)
    return report


@app.patch("/reports/{reference}/triage", response_model=ReportRead, tags=["reports"])
def update_report_triage(
    reference: str, payload: ReportTriageUpdate, db: Session = Depends(get_db)
) -> Report:
    report = db.query(Report).filter(Report.reference == reference).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found")
    area = None
    if payload.area_id is not None:
        area = db.query(Area).filter(Area.id == payload.area_id).first()
        if area is None:
            raise HTTPException(status_code=422, detail="Select a valid area")
    if area is None and not payload.location_uncertain:
        raise HTTPException(status_code=422, detail="Mark the location uncertain when no area is selected")

    old_values = {
        "area": report.area,
        "category": report.category,
        "location_uncertain": report.location_uncertain,
    }
    report.area_ref = area
    report.area = area.name if area else None
    report.category = payload.category
    report.location_uncertain = payload.location_uncertain
    report.triage_reason = payload.reason
    report.triage_actor = "Operations Admin"
    report.triaged_at = datetime.now(timezone.utc)
    report.review_events.append(
        ReportReviewEvent(
            action="triage",
            reason=payload.reason,
            actor="Operations Admin",
            details={
                "before": old_values,
                "after": {
                    "area": report.area,
                    "category": report.category,
                    "location_uncertain": report.location_uncertain,
                },
            },
        )
    )
    db.commit()
    db.refresh(report)
    return report


@app.get("/tasks", response_model=list[TaskRead], tags=["tasks"])
def list_tasks(db: Session = Depends(get_db)) -> list[Task]:
    return list(db.query(Task).order_by(Task.created_at.desc()).all())


def _active_cluster_groups(db: Session) -> dict[tuple[str, int], list[Report]]:
    active_reports = (
        db.query(Report)
        .outerjoin(Task, Task.report_id == Report.id)
        .filter(
            Report.area_id.is_not(None),
            Report.location_uncertain.is_(False),
            Report.category.in_(CLUSTERABLE_REPORT_CATEGORIES),
            Report.disposition.is_(None),
            (Task.id.is_(None))
            | Task.status.in_([TaskStatus.REPORTED, TaskStatus.ASSIGNED, TaskStatus.IN_PROGRESS]),
        )
        .all()
    )
    groups: dict[tuple[str, int], list[Report]] = defaultdict(list)
    for report in active_reports:
        groups[(report.category, report.area_id)].append(report)
    eligible_groups = {key: reports for key, reports in groups.items() if len(reports) >= 2}
    for reports in eligible_groups.values():
        reports.sort(key=lambda item: item.id)
    return eligible_groups


@app.post(
    "/clusters/suggest",
    response_model=ClusterSuggestionResult,
    tags=["possible incident clusters"],
)
def suggest_incident_clusters(db: Session = Depends(get_db)) -> ClusterSuggestionResult:
    # Serialize suggestion refreshes so concurrent coordinator clicks cannot
    # create competing snapshots for the same category and area.
    db.execute(text("SELECT pg_advisory_xact_lock(0, 174821933)"))
    groups = _active_cluster_groups(db)

    existing_clusters = db.query(IncidentCluster).all()
    suggested_by_key: dict[tuple[str, int], list[IncidentCluster]] = defaultdict(list)
    reviewed_fingerprints = {
        cluster.fingerprint
        for cluster in existing_clusters
        if cluster.status != ClusterReviewStatus.SUGGESTED
    }
    for cluster in existing_clusters:
        if cluster.status == ClusterReviewStatus.SUGGESTED:
            suggested_by_key[(cluster.category, cluster.area_id)].append(cluster)

    created = 0
    updated = 0
    removed = 0
    for key, suggestions in suggested_by_key.items():
        candidate = groups.get(key)
        suggestions.sort(key=lambda cluster: cluster.id)
        keeper = suggestions[0]
        for stale_duplicate in suggestions[1:]:
            db.delete(stale_duplicate)
            removed += 1
        if len(suggestions) > 1:
            db.flush()
        if candidate is None:
            db.delete(keeper)
            removed += 1
            continue

        fingerprint = f"{key[0]}:{key[1]}:{','.join(str(item.id) for item in candidate)}"
        # A coordinator has already decided on this exact set. Keep that
        # decision and remove any redundant unreviewed copy.
        if fingerprint in reviewed_fingerprints:
            db.delete(keeper)
            removed += 1
            groups.pop(key, None)
            continue
        if keeper.fingerprint != fingerprint:
            updated += 1
        keeper.fingerprint = fingerprint
        keeper.reports = candidate
        groups.pop(key, None)

    for (category, area_id), reports in groups.items():
        fingerprint = f"{category}:{area_id}:{','.join(str(item.id) for item in reports)}"
        if fingerprint in reviewed_fingerprints:
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

    # Flush deletes before inserting refreshed snapshots with the same unique
    # fingerprint when an obsolete suggestion is replaced by a reviewed state.
    db.flush()
    db.commit()
    return ClusterSuggestionResult(created=created, updated=updated, removed=removed)


@app.get("/clusters", response_model=list[IncidentClusterRead], tags=["possible incident clusters"])
def list_incident_clusters(db: Session = Depends(get_db)) -> list[IncidentCluster]:
    groups = _active_cluster_groups(db)
    clusters = db.query(IncidentCluster).order_by(IncidentCluster.created_at.desc()).all()
    visible = []
    for cluster in clusters:
        if cluster.status != ClusterReviewStatus.SUGGESTED:
            visible.append(cluster)
            continue
        reports = groups.get((cluster.category, cluster.area_id), [])
        if [report.id for report in reports] == sorted(report.id for report in cluster.reports):
            visible.append(cluster)
    return visible


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
    current_reports = _active_cluster_groups(db).get((cluster.category, cluster.area_id), [])
    if [report.id for report in current_reports] != sorted(report.id for report in cluster.reports):
        raise HTTPException(status_code=409, detail="This suggestion is stale; find possible clusters again")

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
    if payload.status in {TaskStatus.IN_PROGRESS, TaskStatus.RESOLVED}:
        is_resolution = payload.status == TaskStatus.RESOLVED
        delivery = send_resolution_sms(task.report) if is_resolution else send_in_progress_sms(task.report)
        update_name = "resolution" if is_resolution else "in-progress"
        if delivery == "accepted":
            outcome = f"{update_name} SMS accepted by Africa's Talking; handset delivery is unconfirmed"
        elif delivery == "simulated":
            outcome = f"{update_name} SMS shown in simulated mode; not delivered"
        else:
            outcome = f"provider send failed; {update_name} update shown in simulated mode"
        status_event.note = f"{payload.note}. {outcome}" if payload.note else outcome.capitalize()
        db.commit()
    db.refresh(task)
    return task
